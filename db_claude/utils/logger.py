"""
Centralized logging setup for db-claude.
Uses Python's built-in logging with RotatingFileHandler.
"""
import os
import logging
from logging.handlers import RotatingFileHandler


def setup_logging(
    level: str = None,
    log_dir: str = None,
) -> None:
    """Configure db-claude logging. Call once at startup.

    Args:
        level: Override log level (DEBUG/INFO/WARNING/ERROR). Default: INFO.
        log_dir: Override log directory. Default: ~/.db-claude/logs/
    """
    level = level or os.environ.get("DB_CLAUDE_LOG_LEVEL", "INFO")
    log_dir = log_dir or os.environ.get(
        "DB_CLAUDE_LOG_DIR",
        os.path.join(os.path.expanduser("~/.db-claude"), "logs"),
    )
    os.makedirs(log_dir, exist_ok=True)

    root = logging.getLogger("db_claude")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # ── File handler: system log (10MB × 5, INFO+) ──
    sys_log = os.path.join(log_dir, "db-claude.log")
    fh = RotatingFileHandler(sys_log, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s:%(funcName)s:%(lineno)d — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(fh)

    # ── Console handler: stderr (DEBUG, compact format) ──
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(logging.Formatter(
        "[%(levelname)-7s] %(name)s: %(message)s"
    ))
    root.addHandler(ch)

    # ── Hook audit log: separate file (50MB × 10, INFO+) ──
    hook_log = os.path.join(log_dir, "hooks.log")
    hh = RotatingFileHandler(hook_log, maxBytes=50 * 1024 * 1024, backupCount=10, encoding="utf-8")
    hh.setLevel(logging.INFO)
    hh.setFormatter(logging.Formatter(
        '{"time":"%(asctime)s","message":"%(message)s"}',
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    # Only hook logger writes to this file
    hook_logger = logging.getLogger("db_claude.hooks")
    hook_logger.addHandler(hh)
    hook_logger.propagate = True  # Also send to root handlers

    # ── Quiet noisy modules ──
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)

    root.debug("Logging configured: level=%s dir=%s", level, log_dir)
