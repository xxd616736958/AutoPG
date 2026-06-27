# ruff: noqa: B008
import argparse
import asyncio
import logging
import os
import signal
import sys
from enum import Enum
from typing import Any
from typing import List
from typing import Literal
from typing import Union

import mcp.types as types
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field
from pydantic import validate_call

from postgres_mcp.index.dta_calc import DatabaseTuningAdvisor
import json

from .artifacts import ErrorResult
from .artifacts import ExplainPlanArtifact
from .database_health import DatabaseHealthTool
from .database_health import HealthType
from .explain import ExplainPlanTool
from .index.index_opt_base import MAX_NUM_INDEX_TUNING_QUERIES
from .index.presentation import TextPresentation
from .sql import DbConnPool
from .sql import SafeSqlDriver
from .sql import SqlDriver
from .sql import check_hypopg_installation_status
from .sql import obfuscate_password
from .top_queries import TopQueriesCalc
from .pgbench import compare_runs, init_pgbench, run_pgbench

# Initialize FastMCP with default settings
mcp = FastMCP("postgres-mcp")

# Constants
PG_STAT_STATEMENTS = "pg_stat_statements"
HYPOPG_EXTENSION = "hypopg"

ResponseType = List[types.TextContent | types.ImageContent | types.EmbeddedResource]

logger = logging.getLogger(__name__)


class AccessMode(str, Enum):
    """SQL access modes for the server."""

    UNRESTRICTED = "unrestricted"  # Unrestricted access
    RESTRICTED = "restricted"  # Read-only with safety features


# Global variables
db_connection = DbConnPool()
current_access_mode = AccessMode.UNRESTRICTED
shutdown_in_progress = False


async def get_sql_driver() -> Union[SqlDriver, SafeSqlDriver]:
    """Get the appropriate SQL driver based on the current access mode."""
    base_driver = SqlDriver(conn=db_connection)

    if current_access_mode == AccessMode.RESTRICTED:
        logger.debug("Using SafeSqlDriver with restrictions (RESTRICTED mode)")
        return SafeSqlDriver(sql_driver=base_driver, timeout=30)  # 30 second timeout
    else:
        logger.debug("Using unrestricted SqlDriver (UNRESTRICTED mode)")
        return base_driver


def get_index_tuning_tool(sql_driver: Union[SqlDriver, SafeSqlDriver], method: Literal["dta", "llm"]):
    if method == "dta":
        return DatabaseTuningAdvisor(sql_driver)

    try:
        from .index.llm_opt import LLMOptimizerTool
    except ImportError as exc:
        raise RuntimeError(
            "LLM index optimizer dependencies are not installed. "
            "Use method='dta' or install the optional LLM optimizer dependencies."
        ) from exc

    return LLMOptimizerTool(sql_driver)


def format_text_response(text: Any) -> ResponseType:
    """Format a text response."""
    return [types.TextContent(type="text", text=str(text))]


def format_error_response(error: str) -> ResponseType:
    """Format an error response."""
    return format_text_response(f"Error: {error}")


@mcp.tool(
    description="List all schemas in the database",
    annotations=ToolAnnotations(
        title="List Schemas",
        readOnlyHint=True,
    ),
)
async def list_schemas() -> ResponseType:
    """List all schemas in the database."""
    try:
        sql_driver = await get_sql_driver()
        rows = await sql_driver.execute_query(
            """
            SELECT
                schema_name,
                schema_owner,
                CASE
                    WHEN schema_name LIKE 'pg_%' THEN 'System Schema'
                    WHEN schema_name = 'information_schema' THEN 'System Information Schema'
                    ELSE 'User Schema'
                END as schema_type
            FROM information_schema.schemata
            ORDER BY schema_type, schema_name
            """
        )
        schemas = [row.cells for row in rows] if rows else []
        return format_text_response(schemas)
    except Exception as e:
        logger.error(f"Error listing schemas: {e}")
        return format_error_response(str(e))


@mcp.tool(
    description="List objects in a schema",
    annotations=ToolAnnotations(
        title="List Objects",
        readOnlyHint=True,
    ),
)
async def list_objects(
    schema_name: str = Field(description="Schema name"),
    object_type: str = Field(description="Object type: 'table', 'view', 'sequence', or 'extension'", default="table"),
) -> ResponseType:
    """List objects of a given type in a schema."""
    try:
        sql_driver = await get_sql_driver()

        if object_type in ("table", "view"):
            table_type = "BASE TABLE" if object_type == "table" else "VIEW"
            rows = await SafeSqlDriver.execute_param_query(
                sql_driver,
                """
                SELECT table_schema, table_name, table_type
                FROM information_schema.tables
                WHERE table_schema = {} AND table_type = {}
                ORDER BY table_name
                """,
                [schema_name, table_type],
            )
            objects = (
                [{"schema": row.cells["table_schema"], "name": row.cells["table_name"], "type": row.cells["table_type"]} for row in rows]
                if rows
                else []
            )

        elif object_type == "sequence":
            rows = await SafeSqlDriver.execute_param_query(
                sql_driver,
                """
                SELECT sequence_schema, sequence_name, data_type
                FROM information_schema.sequences
                WHERE sequence_schema = {}
                ORDER BY sequence_name
                """,
                [schema_name],
            )
            objects = (
                [{"schema": row.cells["sequence_schema"], "name": row.cells["sequence_name"], "data_type": row.cells["data_type"]} for row in rows]
                if rows
                else []
            )

        elif object_type == "extension":
            # Extensions are not schema-specific
            rows = await sql_driver.execute_query(
                """
                SELECT extname, extversion, extrelocatable
                FROM pg_extension
                ORDER BY extname
                """
            )
            objects = (
                [{"name": row.cells["extname"], "version": row.cells["extversion"], "relocatable": row.cells["extrelocatable"]} for row in rows]
                if rows
                else []
            )

        else:
            return format_error_response(f"Unsupported object type: {object_type}")

        return format_text_response(objects)
    except Exception as e:
        logger.error(f"Error listing objects: {e}")
        return format_error_response(str(e))


@mcp.tool(
    description="Show detailed information about a database object",
    annotations=ToolAnnotations(
        title="Get Object Details",
        readOnlyHint=True,
    ),
)
async def get_object_details(
    schema_name: str = Field(description="Schema name"),
    object_name: str = Field(description="Object name"),
    object_type: str = Field(description="Object type: 'table', 'view', 'sequence', or 'extension'", default="table"),
) -> ResponseType:
    """Get detailed information about a database object."""
    try:
        sql_driver = await get_sql_driver()

        if object_type in ("table", "view"):
            # Get columns
            col_rows = await SafeSqlDriver.execute_param_query(
                sql_driver,
                """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = {} AND table_name = {}
                ORDER BY ordinal_position
                """,
                [schema_name, object_name],
            )
            columns = (
                [
                    {
                        "column": r.cells["column_name"],
                        "data_type": r.cells["data_type"],
                        "is_nullable": r.cells["is_nullable"],
                        "default": r.cells["column_default"],
                    }
                    for r in col_rows
                ]
                if col_rows
                else []
            )

            # Get constraints
            con_rows = await SafeSqlDriver.execute_param_query(
                sql_driver,
                """
                SELECT tc.constraint_name, tc.constraint_type, kcu.column_name
                FROM information_schema.table_constraints AS tc
                LEFT JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = {} AND tc.table_name = {}
                """,
                [schema_name, object_name],
            )

            constraints = {}
            if con_rows:
                for row in con_rows:
                    cname = row.cells["constraint_name"]
                    ctype = row.cells["constraint_type"]
                    col = row.cells["column_name"]

                    if cname not in constraints:
                        constraints[cname] = {"type": ctype, "columns": []}
                    if col:
                        constraints[cname]["columns"].append(col)

            constraints_list = [{"name": name, **data} for name, data in constraints.items()]

            # Get indexes
            idx_rows = await SafeSqlDriver.execute_param_query(
                sql_driver,
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = {} AND tablename = {}
                """,
                [schema_name, object_name],
            )

            indexes = [{"name": r.cells["indexname"], "definition": r.cells["indexdef"]} for r in idx_rows] if idx_rows else []

            result = {
                "basic": {"schema": schema_name, "name": object_name, "type": object_type},
                "columns": columns,
                "constraints": constraints_list,
                "indexes": indexes,
            }

        elif object_type == "sequence":
            rows = await SafeSqlDriver.execute_param_query(
                sql_driver,
                """
                SELECT sequence_schema, sequence_name, data_type, start_value, increment
                FROM information_schema.sequences
                WHERE sequence_schema = {} AND sequence_name = {}
                """,
                [schema_name, object_name],
            )

            if rows and rows[0]:
                row = rows[0]
                result = {
                    "schema": row.cells["sequence_schema"],
                    "name": row.cells["sequence_name"],
                    "data_type": row.cells["data_type"],
                    "start_value": row.cells["start_value"],
                    "increment": row.cells["increment"],
                }
            else:
                result = {}

        elif object_type == "extension":
            rows = await SafeSqlDriver.execute_param_query(
                sql_driver,
                """
                SELECT extname, extversion, extrelocatable
                FROM pg_extension
                WHERE extname = {}
                """,
                [object_name],
            )

            if rows and rows[0]:
                row = rows[0]
                result = {"name": row.cells["extname"], "version": row.cells["extversion"], "relocatable": row.cells["extrelocatable"]}
            else:
                result = {}

        else:
            return format_error_response(f"Unsupported object type: {object_type}")

        return format_text_response(result)
    except Exception as e:
        logger.error(f"Error getting object details: {e}")
        return format_error_response(str(e))


@mcp.tool(
    description="Explains the execution plan for a SQL query, showing how the database will execute it and provides detailed cost estimates.",
    annotations=ToolAnnotations(
        title="Explain Query",
        readOnlyHint=True,
    ),
)
async def explain_query(
    sql: str = Field(description="SQL query to explain"),
    analyze: bool = Field(
        description="When True, actually runs the query to show real execution statistics instead of estimates. "
        "Takes longer but provides more accurate information.",
        default=False,
    ),
    hypothetical_indexes: list[dict[str, Any]] = Field(
        description="""A list of hypothetical indexes to simulate. Each index must be a dictionary with these keys:
    - 'table': The table name to add the index to (e.g., 'users')
    - 'columns': List of column names to include in the index (e.g., ['email'] or ['last_name', 'first_name'])
    - 'using': Optional index method (default: 'btree', other options include 'hash', 'gist', etc.)

Examples: [
    {"table": "users", "columns": ["email"], "using": "btree"},
    {"table": "orders", "columns": ["user_id", "created_at"]}
]
If there is no hypothetical index, you can pass an empty list.""",
        default=[],
    ),
) -> ResponseType:
    """
    Explains the execution plan for a SQL query.

    Args:
        sql: The SQL query to explain
        analyze: When True, actually runs the query for real statistics
        hypothetical_indexes: Optional list of indexes to simulate
    """
    try:
        sql_driver = await get_sql_driver()
        explain_tool = ExplainPlanTool(sql_driver=sql_driver)
        result: ExplainPlanArtifact | ErrorResult | None = None

        # If hypothetical indexes are specified, check for HypoPG extension
        if hypothetical_indexes and len(hypothetical_indexes) > 0:
            if analyze:
                return format_error_response("Cannot use analyze and hypothetical indexes together")
            try:
                # Use the common utility function to check if hypopg is installed
                (
                    is_hypopg_installed,
                    hypopg_message,
                ) = await check_hypopg_installation_status(sql_driver)

                # If hypopg is not installed, return the message
                if not is_hypopg_installed:
                    return format_text_response(hypopg_message)

                # HypoPG is installed, proceed with explaining with hypothetical indexes
                result = await explain_tool.explain_with_hypothetical_indexes(sql, hypothetical_indexes)
            except Exception:
                raise  # Re-raise the original exception
        elif analyze:
            try:
                # Use EXPLAIN ANALYZE
                result = await explain_tool.explain_analyze(sql)
            except Exception:
                raise  # Re-raise the original exception
        else:
            try:
                # Use basic EXPLAIN
                result = await explain_tool.explain(sql)
            except Exception:
                raise  # Re-raise the original exception

        if result and isinstance(result, ExplainPlanArtifact):
            return format_text_response(result.to_text())
        else:
            error_message = "Error processing explain plan"
            if isinstance(result, ErrorResult):
                error_message = result.to_text()
            return format_error_response(error_message)
    except Exception as e:
        logger.error(f"Error explaining query: {e}")
        return format_error_response(str(e))


# Query function declaration without the decorator - we'll add it dynamically based on access mode
async def execute_sql(
    sql: str = Field(description="SQL to run", default="all"),
) -> ResponseType:
    """Executes a SQL query against the database."""
    try:
        sql_driver = await get_sql_driver()
        rows = await sql_driver.execute_query(sql)  # type: ignore
        if rows is None:
            return format_text_response("No results")
        return format_text_response(list([r.cells for r in rows]))
    except Exception as e:
        logger.error(f"Error executing query: {e}")
        return format_error_response(str(e))


@mcp.tool(
    description="Analyze frequently executed queries in the database and recommend optimal indexes",
    annotations=ToolAnnotations(
        title="Analyze Workload Indexes",
        readOnlyHint=True,
    ),
)
@validate_call
async def analyze_workload_indexes(
    max_index_size_mb: int = Field(description="Max index size in MB", default=10000),
    method: Literal["dta", "llm"] = Field(description="Method to use for analysis", default="dta"),
) -> ResponseType:
    """Analyze frequently executed queries in the database and recommend optimal indexes."""
    try:
        sql_driver = await get_sql_driver()
        index_tuning = get_index_tuning_tool(sql_driver, method)
        dta_tool = TextPresentation(sql_driver, index_tuning)
        result = await dta_tool.analyze_workload(max_index_size_mb=max_index_size_mb)
        return format_text_response(result)
    except Exception as e:
        logger.error(f"Error analyzing workload: {e}")
        return format_error_response(str(e))


@mcp.tool(
    description="Analyze a list of (up to 10) SQL queries and recommend optimal indexes",
    annotations=ToolAnnotations(
        title="Analyze Query Indexes",
        readOnlyHint=True,
    ),
)
@validate_call
async def analyze_query_indexes(
    queries: list[str] = Field(description="List of Query strings to analyze"),
    max_index_size_mb: int = Field(description="Max index size in MB", default=10000),
    method: Literal["dta", "llm"] = Field(description="Method to use for analysis", default="dta"),
) -> ResponseType:
    """Analyze a list of SQL queries and recommend optimal indexes."""
    if len(queries) == 0:
        return format_error_response("Please provide a non-empty list of queries to analyze.")
    if len(queries) > MAX_NUM_INDEX_TUNING_QUERIES:
        return format_error_response(f"Please provide a list of up to {MAX_NUM_INDEX_TUNING_QUERIES} queries to analyze.")

    try:
        sql_driver = await get_sql_driver()
        index_tuning = get_index_tuning_tool(sql_driver, method)
        dta_tool = TextPresentation(sql_driver, index_tuning)
        result = await dta_tool.analyze_queries(queries=queries, max_index_size_mb=max_index_size_mb)
        return format_text_response(result)
    except Exception as e:
        logger.error(f"Error analyzing queries: {e}")
        return format_error_response(str(e))


@mcp.tool(
    description="Analyzes database health. Here are the available health checks:\n"
    "- index - checks for invalid, duplicate, and bloated indexes\n"
    "- connection - checks the number of connection and their utilization\n"
    "- vacuum - checks vacuum health for transaction id wraparound\n"
    "- sequence - checks sequences at risk of exceeding their maximum value\n"
    "- replication - checks replication health including lag and slots\n"
    "- buffer - checks for buffer cache hit rates for indexes and tables\n"
    "- constraint - checks for invalid constraints\n"
    "- all - runs all checks\n"
    "You can optionally specify a single health check or a comma-separated list of health checks. The default is 'all' checks.",
    annotations=ToolAnnotations(
        title="Analyze Database Health",
        readOnlyHint=True,
    ),
)
async def analyze_db_health(
    health_type: str = Field(
        description=f"Optional. Valid values are: {', '.join(sorted([t.value for t in HealthType]))}.",
        default="all",
    ),
) -> ResponseType:
    """Analyze database health for specified components.

    Args:
        health_type: Comma-separated list of health check types to perform.
                    Valid values: index, connection, vacuum, sequence, replication, buffer, constraint, all
    """
    health_tool = DatabaseHealthTool(await get_sql_driver())
    result = await health_tool.health(health_type=health_type)
    return format_text_response(result)


@mcp.tool(
    name="get_top_queries",
    description=f"Reports the slowest or most resource-intensive queries using data from the '{PG_STAT_STATEMENTS}' extension.",
    annotations=ToolAnnotations(
        title="Get Top Queries",
        readOnlyHint=True,
    ),
)
async def get_top_queries(
    sort_by: str = Field(
        description="Ranking criteria: 'total_time' for total execution time or 'mean_time' for mean execution time per call, or 'resources' "
        "for resource-intensive queries",
        default="resources",
    ),
    limit: int = Field(description="Number of queries to return when ranking based on mean_time or total_time", default=10),
) -> ResponseType:
    try:
        sql_driver = await get_sql_driver()
        top_queries_tool = TopQueriesCalc(sql_driver=sql_driver)

        if sort_by == "resources":
            result = await top_queries_tool.get_top_resource_queries()
            return format_text_response(result)
        elif sort_by == "mean_time" or sort_by == "total_time":
            # Map the sort_by values to what get_top_queries_by_time expects
            result = await top_queries_tool.get_top_queries_by_time(limit=limit, sort_by="mean" if sort_by == "mean_time" else "total")
        else:
            return format_error_response("Invalid sort criteria. Please use 'resources' or 'mean_time' or 'total_time'.")
        return format_text_response(result)
    except Exception as e:
        logger.error(f"Error getting slow queries: {e}")
        return format_error_response(str(e))


# Short aliases used by MCP skills and Claude-style tool names.
mcp.add_tool(
    explain_query,
    name="explain",
    description="Explain a SQL query execution plan",
    annotations=ToolAnnotations(title="Explain Query", readOnlyHint=True),
)
mcp.add_tool(
    analyze_db_health,
    name="health_check",
    description="Run PostgreSQL health checks over pg_stat_* and related views",
    annotations=ToolAnnotations(title="PostgreSQL Health Check", readOnlyHint=True),
)


@mcp.prompt(name="db-tune-instance", description="PostgreSQL instance-level performance tuning — benchmark, analyze, tune, verify")
def db_tune_instance() -> str:
    return """---
name: db-tune-instance
description: PostgreSQL instance-level performance tuning — benchmark, analyze, tune, verify
when_to_use: When the user asks to tune PostgreSQL performance at the instance level
tools: [mcp__postgres__query, mcp__postgres__health_check, mcp__postgres__pgbench_init, mcp__postgres__pgbench_run, mcp__postgres__pgbench_compare, mcp__postgres__pgbench_cleanup, mcp__postgres__propose_change, bash, read]
---

# PostgreSQL Instance Tuning

You are a PostgreSQL performance engineer. Follow this cycle:

## Step 1: Initialize Benchmark Environment
Use `mcp__postgres__pgbench_init` to create pgbench tables. Choose scale_factor based on available disk: 10 small, 50 medium, 100 large.

## Step 2: Establish Baseline
Use `mcp__postgres__pgbench_run` with save_as="baseline". Recommended: clients=10, threads=2, duration_sec=60, warmup_sec=10.

## Step 3: Collect Performance Metrics
Use `mcp__postgres__health_check` and read-only `mcp__postgres__query`, including pg_stat_statements top queries when available.

## Step 4: Analyze and Hypothesize
Identify the PRIMARY bottleneck. Pick ONE tuning action only.

## Step 5: Propose Tuning Action
Use `mcp__postgres__propose_change` with exact config/DDL, rationale, and expected impact. Wait for DBA approval before execution.

## Step 6: Verify
After approval/application, run `mcp__postgres__pgbench_run` with identical parameters, save_as="after_tuning", then `mcp__postgres__pgbench_compare` baseline vs after_tuning.

## Step 7: Decide
Improved and target met: report success. Improved but target not met: repeat from Step 3. Regressed: roll back and report. No change: revise hypothesis. Stop after 3 cycles without significant improvement.

## Final Report Format
Tuning Report: [Target Database]
Date: [date]
DBA Reviewer: [name]
Baseline Metrics table; Changes Applied; Final Metrics comparison; Recommendations.
"""


@mcp.prompt(name="db-tune-sql", description="SQL query tuning — analyze execution plan, rewrite, index, verify")
def db_tune_sql(query_or_id: str = "") -> str:
    return f"""---
name: db-tune-sql
description: SQL query tuning — analyze execution plan, rewrite, index, verify
when_to_use: When the user asks to tune a specific SQL query or slow query
tools: [mcp__postgres__query, mcp__postgres__explain, mcp__postgres__pgbench_run, mcp__postgres__pgbench_compare, mcp__postgres__propose_change, bash, read]
argument_hint: "<the slow SQL query or query_id from pg_stat_statements>"
---

# SQL Query Tuning

Target query or query_id: {query_or_id}

You are a SQL optimization specialist. Follow this cycle:

## Step 1: Understand the Query
If given a query_id, retrieve query text from pg_stat_statements. If given literal SQL, proceed directly.

## Step 2: Analyze the Execution Plan
Use `mcp__postgres__explain` (prefer analyze when safe) and inspect scans, joins, index usage, and row estimate errors.

## Step 3: Collect Table Statistics
Use read-only `mcp__postgres__query` for pg_stat_user_tables, pg_indexes, and pg_stats for referenced tables.

## Step 4: Benchmark Current Query
Use `mcp__postgres__pgbench_run` with script="custom" and custom_sql containing the target query. Save as before_optimization.

## Step 5: Formulate ONE Optimization Strategy
Choose one: add index, rewrite query, update statistics, adjust work_mem, or materialized view.

## Step 6: Propose Optimization
Use `mcp__postgres__propose_change` with exact DDL/query rewrite, rationale from plan, and expected improvement. Wait for DBA approval.

## Step 7: Verify
Run same custom pgbench parameters save_as="after_optimization", then compare before_optimization vs after_optimization.

## Step 8: Decide
Improved and target met: report success. Improved but not met: try next strategy. Regression: roll back. Stop after 3 cycles without improvement.

## Final Report Format
SQL Tuning Report: [Query Identifier]
Original Query; Execution Plan Before; Optimizations Applied; Performance Comparison; Recommendations.
"""


@mcp.tool(
    description="Initialize pgbench benchmark tables in the target database.",
    annotations=ToolAnnotations(title="Initialize pgbench", destructiveHint=True),
)
async def pgbench_init(
    database: str = Field(description="Target database name for pgbench tables"),
    scale_factor: int = Field(default=10, description="Scale factor (1 ≈ 15MB, 100 ≈ 1.5GB)"),
    foreign_keys: bool = Field(default=True, description="Include foreign key constraints"),
) -> ResponseType:
    """Initialize pgbench tables before benchmarking."""
    try:
        result = await init_pgbench(db_connection, database, scale_factor, foreign_keys)
        return format_text_response(json.dumps(result, indent=2, default=str))
    except Exception as e:
        logger.error(f"Error initializing pgbench: {e}")
        return format_error_response(str(e))


@mcp.tool(
    description="Run pgbench with warmup and return structured performance metrics.",
    annotations=ToolAnnotations(title="Run pgbench", readOnlyHint=True),
)
async def pgbench_run(
    database: str = Field(description="Target database"),
    clients: int = Field(default=10, description="Number of concurrent clients"),
    threads: int = Field(default=2, description="Number of worker threads"),
    duration_sec: int = Field(default=60, description="Benchmark duration in seconds"),
    warmup_sec: int = Field(default=10, description="Warmup duration (excluded from results)"),
    script: str = Field(default="tpcb-like", description="Built-in: tpcb-like, simple-update, select-only, or custom"),
    save_as: str = Field(default="latest", description="Label to save results for comparison"),
    custom_sql: str | None = Field(default=None, description="SQL script text when script='custom'"),
) -> ResponseType:
    """Run pgbench and save the normalized results under a label."""
    try:
        sql_driver = await get_sql_driver()
        result = await run_pgbench(
            db_connection, sql_driver, database, clients, threads, duration_sec, warmup_sec, script, save_as, custom_sql
        )
        return format_text_response(json.dumps(result.__dict__, indent=2, default=str))
    except Exception as e:
        logger.error(f"Error running pgbench: {e}")
        return format_error_response(str(e))


@mcp.tool(
    description="Compare two saved pgbench runs and return TPS/latency deltas with a verdict.",
    annotations=ToolAnnotations(title="Compare pgbench runs", readOnlyHint=True),
)
async def pgbench_compare(
    run_a: str = Field(description="Label of first run (e.g., 'baseline')"),
    run_b: str = Field(description="Label of second run (e.g., 'after_tuning')"),
) -> ResponseType:
    """Compare two pgbench runs."""
    try:
        return format_text_response(json.dumps(compare_runs(run_a, run_b), indent=2, default=str))
    except Exception as e:
        logger.error(f"Error comparing pgbench runs: {e}")
        return format_error_response(str(e))


@mcp.tool(
    description="Drop pgbench tables and free disk space after tuning is complete.",
    annotations=ToolAnnotations(title="Clean pgbench", destructiveHint=True),
)
async def pgbench_cleanup(
    database: str = Field(description="Target database to clean"),
) -> ResponseType:
    """Drop pgbench benchmark tables."""
    try:
        # The MCP server process is already connected to the benchmark target database.
        # The database argument is echoed for the agent/report.
        sql_driver = SqlDriver(conn=db_connection)
        await sql_driver.execute_query(
            "DROP TABLE IF EXISTS pgbench_history, pgbench_tellers, pgbench_accounts, pgbench_branches CASCADE"
        )
        return format_text_response(json.dumps({"database": database, "dropped": True}, indent=2))
    except Exception as e:
        logger.error(f"Error cleaning pgbench tables: {e}")
        return format_error_response(str(e))


@mcp.tool(
    description="Submit a proposed DDL/DML/config change for DBA approval. Does not execute the change.",
    annotations=ToolAnnotations(title="Propose Change", readOnlyHint=True),
)
async def propose_change(
    change: str = Field(description="Exact DDL/DML/config change to propose"),
    rationale: str = Field(description="Why this change is recommended"),
    expected_impact: str = Field(description="Expected performance impact"),
) -> ResponseType:
    """Record a proposed change for human DBA approval."""
    proposal = {
        "status": "pending_approval",
        "change": change,
        "rationale": rationale,
        "expected_impact": expected_impact,
        "message": "Proposal recorded. Wait for DBA approval before execution.",
    }
    return format_text_response(json.dumps(proposal, indent=2))


async def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="PostgreSQL MCP Server")
    parser.add_argument("database_url", help="Database connection URL", nargs="?")
    parser.add_argument(
        "--access-mode",
        type=str,
        choices=[mode.value for mode in AccessMode],
        default=AccessMode.UNRESTRICTED.value,
        help="Set SQL access mode: unrestricted (unrestricted) or restricted (read-only with protections)",
    )
    parser.add_argument(
        "--transport",
        type=str,
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Select MCP transport: stdio (default), sse, or streamable-http",
    )
    parser.add_argument(
        "--sse-host",
        type=str,
        default="localhost",
        help="Host to bind SSE server to (default: localhost)",
    )
    parser.add_argument(
        "--sse-port",
        type=int,
        default=8000,
        help="Port for SSE server (default: 8000)",
    )
    parser.add_argument(
        "--streamable-http-host",
        type=str,
        default="localhost",
        help="Host to bind streamable HTTP server to (default: localhost)",
    )
    parser.add_argument(
        "--streamable-http-port",
        type=int,
        default=8000,
        help="Port for streamable HTTP server (default: 8000)",
    )

    args = parser.parse_args()

    # Store the access mode in the global variable
    global current_access_mode
    current_access_mode = AccessMode(args.access_mode)

    # Add the query tool with a description and annotations appropriate to the access mode
    if current_access_mode == AccessMode.UNRESTRICTED:
        sql_annotations = ToolAnnotations(
            title="Execute SQL",
            destructiveHint=True,
        )
        mcp.add_tool(
            execute_sql,
            description="Execute any SQL query",
            annotations=sql_annotations,
        )
        mcp.add_tool(
            execute_sql,
            name="query",
            description="Execute any SQL query",
            annotations=sql_annotations,
        )
    else:
        sql_annotations = ToolAnnotations(
            title="Execute SQL (Read-Only)",
            readOnlyHint=True,
        )
        mcp.add_tool(
            execute_sql,
            description="Execute a read-only SQL query",
            annotations=sql_annotations,
        )
        mcp.add_tool(
            execute_sql,
            name="query",
            description="Execute a read-only SQL query",
            annotations=sql_annotations,
        )

    logger.info(f"Starting PostgreSQL MCP Server in {current_access_mode.upper()} mode")

    # Get database URL from environment variable or command line
    database_url = os.environ.get("DATABASE_URI", args.database_url)

    if not database_url:
        raise ValueError(
            "Error: No database URL provided. Please specify via 'DATABASE_URI' environment variable or command-line argument.",
        )

    # Initialize database connection pool
    try:
        await db_connection.pool_connect(database_url)
        logger.info("Successfully connected to database and initialized connection pool")
    except Exception as e:
        logger.warning(
            f"Could not connect to database: {obfuscate_password(str(e))}",
        )
        logger.warning(
            "The MCP server will start but database operations will fail until a valid connection is established.",
        )

    # Set up proper shutdown handling
    try:
        loop = asyncio.get_running_loop()
        signals = (signal.SIGTERM, signal.SIGINT)
        for s in signals:
            loop.add_signal_handler(s, lambda s=s: asyncio.create_task(shutdown(s)))
    except NotImplementedError:
        # Windows doesn't support signals properly
        logger.warning("Signal handling not supported on Windows")
        pass

    # Run the server with the selected transport (always async)
    if args.transport == "stdio":
        await mcp.run_stdio_async()
    elif args.transport == "sse":
        mcp.settings.host = args.sse_host
        mcp.settings.port = args.sse_port
        await mcp.run_sse_async()
    elif args.transport == "streamable-http":
        mcp.settings.host = args.streamable_http_host
        mcp.settings.port = args.streamable_http_port
        await mcp.run_streamable_http_async()


async def shutdown(sig=None):
    """Clean shutdown of the server."""
    global shutdown_in_progress

    if shutdown_in_progress:
        logger.warning("Forcing immediate exit")
        # Use sys.exit instead of os._exit to allow for proper cleanup
        sys.exit(1)

    shutdown_in_progress = True

    if sig:
        logger.info(f"Received exit signal {sig.name}")

    # Close database connections
    try:
        await db_connection.close()
        logger.info("Closed database connections")
    except Exception as e:
        logger.error(f"Error closing database connections: {e}")

    # Exit with appropriate status code
    sys.exit(128 + sig if sig is not None else 0)
