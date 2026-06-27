"""pgbench lifecycle tools for postgres_mcp."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from .sql import DbConnPool, SafeSqlDriver, SqlDriver


@dataclass
class PgbenchRun:
    run_id: str
    label: str
    database: str
    config: dict[str, Any]
    metrics: dict[str, Any]
    system_snapshot: dict[str, Any]


class PgbenchStore:
    def __init__(self) -> None:
        root = os.environ.get("POSTGRES_MCP_PGBENCH_STORE") or os.path.join(
            tempfile.gettempdir(), "postgres_mcp_pgbench_runs"
        )
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, run: PgbenchRun) -> None:
        (self.root / f"{run.label}.json").write_text(json.dumps(asdict(run), indent=2, default=str), encoding="utf-8")
        (self.root / f"{run.run_id}.json").write_text(json.dumps(asdict(run), indent=2, default=str), encoding="utf-8")

    def load(self, label_or_id: str) -> dict[str, Any]:
        path = self.root / f"{label_or_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"pgbench run not found: {label_or_id}")
        return json.loads(path.read_text(encoding="utf-8"))


def connection_url_for_database(pool: DbConnPool, database: str) -> str:
    url = os.environ.get("DATABASE_URI") or pool.connection_url
    if not url:
        raise ValueError("DATABASE_URI is required to run pgbench")
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        return urlunparse(parsed._replace(path=f"/{database}"))
    # libpq keyword DSNs are passed through; pgbench -d database will use the dbname there if present.
    return url


async def run_command(args: list[str], timeout: int | None = None) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return proc.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")


def script_args(script: str, custom_sql: str | None, workdir: Path) -> list[str]:
    normalized = script.strip().lower()
    builtins = {"tpcb-like", "simple-update", "select-only"}
    if normalized == "custom":
        if not custom_sql:
            raise ValueError("custom_sql is required when script='custom'")
        script_path = workdir / "custom.sql"
        script_path.write_text(custom_sql, encoding="utf-8")
        return ["-f", str(script_path)]
    if normalized not in builtins:
        raise ValueError(f"Unsupported pgbench script: {script}. Use tpcb-like, simple-update, select-only, or custom.")
    return ["-b", normalized]


def parse_pgbench_output(output: str, log_dir: Path | None = None) -> dict[str, Any]:
    def f(pattern: str, default: float = 0.0) -> float:
        m = re.search(pattern, output, re.IGNORECASE | re.MULTILINE)
        return float(m.group(1)) if m else default

    tps = f(r"^tps\s*=\s*([0-9.]+)")
    avg_latency = f(r"latency average\s*=\s*([0-9.]+)\s*ms")
    total_tx = int(f(r"number of transactions actually processed:\s*(\d+)", 0))
    failed_tx = int(f(r"number of failed transactions:\s*(\d+)", 0))

    latencies_ms: list[float] = []
    if log_dir:
        for file in log_dir.glob("pgbench_log*"):
            try:
                for line in file.read_text(encoding="utf-8", errors="ignore").splitlines():
                    parts = line.split()
                    if len(parts) >= 3:
                        # pgbench transaction log: client tx latency_us ...
                        latencies_ms.append(float(parts[2]) / 1000.0)
            except OSError:
                pass
    latencies_ms.sort()

    def pct(p: float) -> float:
        if not latencies_ms:
            return avg_latency
        idx = min(len(latencies_ms) - 1, max(0, int(round((p / 100.0) * (len(latencies_ms) - 1)))))
        return round(latencies_ms[idx], 3)

    deadlocks = len(re.findall(r"deadlock", output, re.IGNORECASE))
    conn_errors = len(re.findall(r"connection.*(?:error|failed|failure)", output, re.IGNORECASE))
    return {
        "tps": tps,
        "avg_latency_ms": avg_latency,
        "p50_latency_ms": pct(50),
        "p95_latency_ms": pct(95),
        "p99_latency_ms": pct(99),
        "total_transactions": total_tx,
        "connection_errors": conn_errors,
        "deadlock_errors": deadlocks,
        "failed_transactions": failed_tx,
    }


async def system_snapshot(sql_driver: SqlDriver | SafeSqlDriver) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "avg_cpu_pct": None,
        "avg_memory_pct": None,
        "peak_connections": None,
        "checkpoint_count": None,
        "temp_files_bytes": None,
    }
    try:
        import psutil  # type: ignore

        snapshot["avg_cpu_pct"] = psutil.cpu_percent(interval=0.2)
        snapshot["avg_memory_pct"] = psutil.virtual_memory().percent
    except Exception:
        pass

    async def scalar(sql: str) -> Any:
        try:
            rows = await sql_driver.execute_query(sql, force_readonly=True)
            if rows and rows[0].cells:
                return next(iter(rows[0].cells.values()))
        except Exception:
            return None
        return None

    snapshot["peak_connections"] = await scalar("SELECT count(*) FROM pg_stat_activity")
    snapshot["temp_files_bytes"] = await scalar("SELECT COALESCE(sum(temp_bytes), 0) FROM pg_stat_database")

    # PostgreSQL 17 moved checkpoint counters from pg_stat_bgwriter to
    # pg_stat_checkpointer. Probe the catalog first to avoid noisy column errors.
    checkpoint_sql = """
        SELECT CASE
          WHEN to_regclass('pg_catalog.pg_stat_checkpointer') IS NOT NULL THEN
            (SELECT COALESCE(num_timed, 0) + COALESCE(num_requested, 0) FROM pg_stat_checkpointer)
          WHEN to_regclass('pg_catalog.pg_stat_bgwriter') IS NOT NULL
           AND EXISTS (
             SELECT 1 FROM pg_attribute
             WHERE attrelid = 'pg_catalog.pg_stat_bgwriter'::regclass
               AND attname = 'checkpoints_timed'
           ) THEN
            (SELECT COALESCE(checkpoints_timed, 0) + COALESCE(checkpoints_req, 0) FROM pg_stat_bgwriter)
          ELSE NULL
        END
    """
    snapshot["checkpoint_count"] = await scalar(checkpoint_sql)
    return snapshot


async def init_pgbench(pool: DbConnPool, database: str, scale_factor: int, foreign_keys: bool) -> dict[str, Any]:
    url = connection_url_for_database(pool, database)
    args = ["pgbench", "-i", "-s", str(scale_factor)]
    if foreign_keys:
        args.append("--foreign-keys")
    args.append(url)
    code, out, err = await run_command(args, timeout=max(300, scale_factor * 20))
    if code != 0:
        raise RuntimeError(err or out)
    return {
        "database": database,
        "scale_factor": scale_factor,
        "foreign_keys": foreign_keys,
        "tables": ["pgbench_accounts", "pgbench_branches", "pgbench_tellers", "pgbench_history"],
        "estimated_data_size_mb": round(scale_factor * 15, 1),
        "output": out.strip() or err.strip(),
    }


async def run_pgbench(
    pool: DbConnPool,
    sql_driver: SqlDriver | SafeSqlDriver,
    database: str,
    clients: int,
    threads: int,
    duration_sec: int,
    warmup_sec: int,
    script: str,
    save_as: str,
    custom_sql: str | None = None,
) -> PgbenchRun:
    url = connection_url_for_database(pool, database)
    with tempfile.TemporaryDirectory(prefix="postgres_mcp_pgbench_") as td:
        workdir = Path(td)
        script_part = script_args(script, custom_sql, workdir)
        common = ["pgbench", "-c", str(clients), "-j", str(threads), *script_part]
        if warmup_sec > 0:
            code, out, err = await run_command([*common, "-T", str(warmup_sec), url], timeout=warmup_sec + 60)
            if code != 0:
                raise RuntimeError((out + "\n" + err).strip())
        before = await system_snapshot(sql_driver)
        log_prefix = str(workdir / "pgbench_log")
        code, out, err = await run_command(
            [*common, "-T", str(duration_sec), "-r", "-l", "--log-prefix", log_prefix, url],
            timeout=duration_sec + 120,
        )
        after = await system_snapshot(sql_driver)
        output = out + "\n" + err
        if code != 0:
            raise RuntimeError(output.strip())
        metrics = parse_pgbench_output(output, workdir)

    snapshot = {k: after.get(k) if after.get(k) is not None else before.get(k) for k in set(before) | set(after)}
    run_id = f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 1000:03d}"
    run = PgbenchRun(
        run_id=run_id,
        label=save_as,
        database=database,
        config={
            "clients": clients,
            "threads": threads,
            "duration_sec": duration_sec,
            "warmup_sec": warmup_sec,
            "script": script,
        },
        metrics=metrics,
        system_snapshot=snapshot,
    )
    PgbenchStore().save(run)
    return run


def compare_runs(run_a: str, run_b: str) -> dict[str, Any]:
    store = PgbenchStore()
    a = store.load(run_a)
    b = store.load(run_b)

    def pct(new: float, old: float) -> float | None:
        if old == 0:
            return None
        return round(((new - old) / old) * 100.0, 2)

    changes = {
        "tps_pct": pct(float(b["metrics"].get("tps") or 0), float(a["metrics"].get("tps") or 0)),
        "avg_latency_pct": pct(float(b["metrics"].get("avg_latency_ms") or 0), float(a["metrics"].get("avg_latency_ms") or 0)),
        "p95_latency_pct": pct(float(b["metrics"].get("p95_latency_ms") or 0), float(a["metrics"].get("p95_latency_ms") or 0)),
    }
    tps_change = changes["tps_pct"] or 0
    latency_change = changes["avg_latency_pct"] or 0
    if tps_change >= 5 and latency_change <= 5:
        verdict = "improved"
    elif tps_change <= -5 or latency_change >= 10:
        verdict = "regressed"
    else:
        verdict = "no_change"
    return {
        "run_a": {"label": a["label"], "tps": a["metrics"].get("tps")},
        "run_b": {"label": b["label"], "tps": b["metrics"].get("tps")},
        "changes": changes,
        "verdict": verdict,
        "notes": f"TPS change {changes['tps_pct']}%, average latency change {changes['avg_latency_pct']}%.",
    }
