import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any

import aiosqlite
from config import TRACE_DB_PATH

TRACE_DB_NAME = TRACE_DB_PATH

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _preview(text: str, limit: int = 300) -> str:
    collapsed = " ".join(text.split())
    return collapsed[:limit]


async def init_trace_db() -> None:
    trace_dir = os.path.dirname(TRACE_DB_NAME)
    if trace_dir:
        os.makedirs(trace_dir, exist_ok=True)
    async with aiosqlite.connect(TRACE_DB_NAME) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_runs (
                run_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                finished_at TEXT,
                model TEXT,
                status TEXT NOT NULL,
                final_score INTEGER,
                total_latency_ms INTEGER,
                error TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                step_name TEXT NOT NULL,
                model TEXT NOT NULL,
                latency_ms INTEGER,
                input_tokens INTEGER,
                output_tokens INTEGER,
                status TEXT NOT NULL,
                error TEXT,
                input_hash TEXT,
                output_hash TEXT,
                input_preview TEXT,
                output_preview TEXT
            )
            """
        )
        await db.commit()


async def start_run(run_id: str, model: str) -> None:
    try:
        await init_trace_db()
        async with aiosqlite.connect(TRACE_DB_NAME) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO llm_runs
                (run_id, created_at, model, status)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, _utc_now(), model, "running"),
            )
            await db.commit()
    except Exception as exc:
        logger.warning("Failed to start trace run %s: %s", run_id, exc)


async def finish_run(
    run_id: str,
    status: str,
    final_score: int | None = None,
    total_latency_ms: int | None = None,
    error: str | None = None,
) -> None:
    try:
        await init_trace_db()
        async with aiosqlite.connect(TRACE_DB_NAME) as db:
            await db.execute(
                """
                UPDATE llm_runs
                SET finished_at = ?, status = ?, final_score = ?, total_latency_ms = ?, error = ?
                WHERE run_id = ?
                """,
                (_utc_now(), status, final_score, total_latency_ms, error, run_id),
            )
            await db.commit()
    except Exception as exc:
        logger.warning("Failed to finish trace run %s: %s", run_id, exc)


async def record_step(
    run_id: str,
    step_name: str,
    model: str,
    input_text: str,
    output_text: str = "",
    latency_ms: int | None = None,
    usage: Any = None,
    status: str = "ok",
    error: str | None = None,
) -> None:
    try:
        await init_trace_db()
        input_tokens = getattr(usage, "prompt_tokens", None) if usage else None
        output_tokens = getattr(usage, "completion_tokens", None) if usage else None

        async with aiosqlite.connect(TRACE_DB_NAME) as db:
            await db.execute(
                """
                INSERT INTO llm_steps (
                    run_id, created_at, step_name, model, latency_ms,
                    input_tokens, output_tokens, status, error,
                    input_hash, output_hash, input_preview, output_preview
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    _utc_now(),
                    step_name,
                    model,
                    latency_ms,
                    input_tokens,
                    output_tokens,
                    status,
                    error,
                    _text_hash(input_text),
                    _text_hash(output_text) if output_text else None,
                    _preview(input_text),
                    _preview(output_text) if output_text else "",
                ),
            )
            await db.commit()
    except Exception as exc:
        logger.warning("Failed to record trace step %s/%s: %s", run_id, step_name, exc)
