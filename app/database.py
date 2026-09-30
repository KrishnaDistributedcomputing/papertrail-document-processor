"""Persist document runs and results in a local SQLite database."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.customers import CUSTOMERS, get_customer


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(settings.database_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def _ensure_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    """Add a column when upgrading an existing SQLite database."""
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def initialize_database() -> None:
    """Create the local history database and indexes when needed."""
    with closing(_connect()) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS document_runs (
                job_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL UNIQUE,
                batch_id TEXT,
                customer_id TEXT NOT NULL DEFAULT 'microsoft',
                filename TEXT NOT NULL,
                source_path TEXT NOT NULL,
                result_path TEXT,
                status TEXT NOT NULL,
                stage TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                processing_status TEXT,
                category TEXT,
                page_count INTEGER,
                size_bytes INTEGER,
                sha256 TEXT,
                text_sources_json TEXT,
                analysis_status TEXT,
                analysis_model TEXT,
                cloud_status TEXT,
                cloud_bytes INTEGER,
                estimated_cost_usd REAL,
                warning_count INTEGER NOT NULL DEFAULT 0,
                result_json TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT
            )
            """
        )
        _ensure_column(
            connection,
            "document_runs",
            "customer_id",
            "TEXT NOT NULL DEFAULT 'microsoft'",
        )
        _ensure_column(connection, "document_runs", "cloud_status", "TEXT")
        _ensure_column(connection, "document_runs", "cloud_bytes", "INTEGER")
        _ensure_column(connection, "document_runs", "estimated_cost_usd", "REAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS customer_settings (
                customer_id TEXT PRIMARY KEY,
                retention_days INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        now = _timestamp()
        connection.executemany(
            """
            INSERT OR IGNORE INTO customer_settings (customer_id, retention_days, updated_at)
            VALUES (?, ?, ?)
            """,
            [
                (customer.id, customer.default_retention_days, now)
                for customer in CUSTOMERS
            ],
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_document_runs_created_at "
            "ON document_runs(created_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_document_runs_batch_id "
            "ON document_runs(batch_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_document_runs_customer_id "
            "ON document_runs(customer_id, created_at DESC)"
        )
        connection.commit()


def create_run(
    *,
    job_id: str,
    document_id: str,
    batch_id: str | None,
    customer_id: str = "microsoft",
    filename: str,
    source_path: Path,
) -> None:
    """Store a queued document before publishing it to the worker."""
    if get_customer(customer_id) is None:
        raise ValueError(f"Unknown customer: {customer_id}")
    initialize_database()
    now = _timestamp()
    with closing(_connect()) as connection:
        connection.execute(
            """
            INSERT INTO document_runs (
                job_id, document_id, batch_id, customer_id, filename, source_path,
                status, stage, progress, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'queued', 'queued', 0, ?, ?)
            """,
            (
                job_id,
                document_id,
                batch_id,
                customer_id,
                filename,
                str(source_path),
                now,
                now,
            ),
        )
        connection.commit()


def update_run(
    job_id: str,
    *,
    status: str,
    stage: str,
    progress: int,
    error: str | None = None,
) -> None:
    """Persist the latest known processing state for a document run."""
    with closing(_connect()) as connection:
        connection.execute(
            """
            UPDATE document_runs
            SET status = ?, stage = ?, progress = ?, error = ?, updated_at = ?
            WHERE job_id = ?
            """,
            (status, stage, max(0, min(progress, 100)), error, _timestamp(), job_id),
        )
        connection.commit()


def complete_run(job_id: str, result_path: Path, result: dict[str, Any]) -> None:
    """Persist a completed result and its searchable summary fields."""
    document = result.get("document", {})
    processing = result.get("processing", {})
    analysis = result.get("analysis", {})
    storage = result.get("storage", {})
    cost_estimate = result.get("cost_estimate", {})
    text_sources = [page.get("text_source", "none") for page in result.get("pages", [])]
    now = _timestamp()
    with closing(_connect()) as connection:
        connection.execute(
            """
            UPDATE document_runs
            SET result_path = ?, status = 'completed', stage = 'completed', progress = 100,
                processing_status = ?, category = ?, page_count = ?, size_bytes = ?,
                sha256 = ?, text_sources_json = ?, analysis_status = ?, analysis_model = ?,
                cloud_status = ?, cloud_bytes = ?, estimated_cost_usd = ?, warning_count = ?,
                result_json = ?, error = NULL, updated_at = ?, completed_at = ?
            WHERE job_id = ?
            """,
            (
                str(result_path),
                processing.get("status", "completed"),
                document.get("classification", {}).get("category"),
                document.get("page_count"),
                document.get("size_bytes"),
                document.get("sha256"),
                json.dumps(text_sources),
                analysis.get("status"),
                analysis.get("model"),
                storage.get("status"),
                cost_estimate.get("stored_bytes"),
                cost_estimate.get("estimated_total_usd"),
                len(processing.get("warnings", [])),
                json.dumps(result, ensure_ascii=False),
                now,
                now,
                job_id,
            ),
        )
        connection.commit()


def fail_run(job_id: str, error: str) -> None:
    """Store a terminal processing failure."""
    update_run(job_id, status="failed", stage="failed", progress=0, error=error)


def cancel_run(job_id: str) -> None:
    """Store a terminal cancellation."""
    update_run(job_id, status="cancelled", stage="cancelled", progress=0)


def _public_run(row: sqlite3.Row) -> dict[str, Any]:
    text_sources = json.loads(row["text_sources_json"] or "[]")
    return {
        "job_id": row["job_id"],
        "document_id": row["document_id"],
        "batch_id": row["batch_id"],
        "customer_id": row["customer_id"],
        "filename": row["filename"],
        "status": row["status"],
        "stage": row["stage"],
        "progress": row["progress"],
        "processing_status": row["processing_status"],
        "category": row["category"],
        "page_count": row["page_count"],
        "size_bytes": row["size_bytes"],
        "sha256": row["sha256"],
        "text_sources": text_sources,
        "analysis_status": row["analysis_status"],
        "analysis_model": row["analysis_model"],
        "cloud_status": row["cloud_status"],
        "cloud_bytes": row["cloud_bytes"],
        "estimated_cost_usd": row["estimated_cost_usd"],
        "warning_count": row["warning_count"],
        "error": "Document processing failed. Check the worker logs for details." if row["error"] else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
        "result_available": row["result_json"] is not None,
    }


def get_run(job_id: str) -> dict[str, Any] | None:
    """Return one durable run by job ID."""
    initialize_database()
    with closing(_connect()) as connection:
        row = connection.execute(
            "SELECT * FROM document_runs WHERE job_id = ?", (job_id,)
        ).fetchone()
    return _public_run(row) if row else None


def list_runs(
    *,
    limit: int = 20,
    offset: int = 0,
    customer_id: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Return recent durable runs and their total count."""
    initialize_database()
    bounded_limit = max(1, min(limit, 100))
    bounded_offset = max(0, offset)
    with closing(_connect()) as connection:
        if customer_id:
            rows = connection.execute(
                """
                SELECT * FROM document_runs
                WHERE customer_id = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT ? OFFSET ?
                """,
                (customer_id, bounded_limit, bounded_offset),
            ).fetchall()
            total = connection.execute(
                "SELECT COUNT(*) FROM document_runs WHERE customer_id = ?",
                (customer_id,),
            ).fetchone()[0]
        else:
            rows = connection.execute(
                """
                SELECT * FROM document_runs
                ORDER BY created_at DESC, rowid DESC
                LIMIT ? OFFSET ?
                """,
                (bounded_limit, bounded_offset),
            ).fetchall()
            total = connection.execute("SELECT COUNT(*) FROM document_runs").fetchone()[0]
    return [_public_run(row) for row in rows], int(total)


def get_customer_retention(customer_id: str) -> int:
    """Return the configured retention period for a customer."""
    initialize_database()
    with closing(_connect()) as connection:
        row = connection.execute(
            "SELECT retention_days FROM customer_settings WHERE customer_id = ?",
            (customer_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"Unknown customer: {customer_id}")
    return int(row["retention_days"])


def set_customer_retention(customer_id: str, retention_days: int) -> int:
    """Persist a customer's document retention period."""
    if get_customer(customer_id) is None:
        raise ValueError(f"Unknown customer: {customer_id}")
    if not 1 <= retention_days <= 3650:
        raise ValueError("Retention must be between 1 and 3650 days.")
    initialize_database()
    with closing(_connect()) as connection:
        connection.execute(
            """
            UPDATE customer_settings
            SET retention_days = ?, updated_at = ?
            WHERE customer_id = ?
            """,
            (retention_days, _timestamp(), customer_id),
        )
        connection.commit()
    return retention_days


def list_customer_settings() -> dict[str, int]:
    """Return retention settings keyed by customer identifier."""
    initialize_database()
    with closing(_connect()) as connection:
        rows = connection.execute(
            "SELECT customer_id, retention_days FROM customer_settings"
        ).fetchall()
    return {str(row["customer_id"]): int(row["retention_days"]) for row in rows}


def customer_run_summaries() -> dict[str, dict[str, int | float]]:
    """Aggregate processed document counts, bytes, and estimates by customer."""
    initialize_database()
    with closing(_connect()) as connection:
        rows = connection.execute(
            """
            SELECT customer_id,
                   COUNT(*) AS document_count,
                   COALESCE(SUM(size_bytes), 0) AS source_bytes,
                   COALESCE(SUM(cloud_bytes), 0) AS cloud_bytes,
                   COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd
            FROM document_runs
            GROUP BY customer_id
            """
        ).fetchall()
    return {
        str(row["customer_id"]): {
            "document_count": int(row["document_count"]),
            "source_bytes": int(row["source_bytes"]),
            "cloud_bytes": int(row["cloud_bytes"]),
            "estimated_cost_usd": round(float(row["estimated_cost_usd"]), 6),
        }
        for row in rows
    }


def customer_cost_summaries() -> dict[str, dict[str, int | float | str | None]]:
    """Aggregate persisted cost components for completed customer runs."""
    initialize_database()
    with closing(_connect()) as connection:
        rows = connection.execute(
            """
            SELECT customer_id, cloud_bytes, estimated_cost_usd, result_json, completed_at
            FROM document_runs
            WHERE status = 'completed'
            ORDER BY completed_at
            """
        ).fetchall()

    summaries: dict[str, dict[str, int | float | str | None]] = {}
    for row in rows:
        customer_id = str(row["customer_id"])
        summary = summaries.setdefault(
            customer_id,
            {
                "document_count": 0,
                "stored_bytes": 0,
                "runtime_ms": 0,
                "compute_usd": 0.0,
                "storage_for_retention_usd": 0.0,
                "transactions_usd": 0.0,
                "estimated_total_usd": 0.0,
                "first_completed_at": None,
                "last_completed_at": None,
            },
        )
        try:
            result = json.loads(row["result_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            result = {}
        cost = result.get("cost_estimate", {}) if isinstance(result, dict) else {}
        if not isinstance(cost, dict):
            cost = {}

        compute = max(0.0, float(cost.get("compute_usd") or 0))
        storage = max(0.0, float(cost.get("storage_for_retention_usd") or 0))
        transactions = max(0.0, float(cost.get("transactions_usd") or 0))
        stored_bytes = max(0, int(cost.get("stored_bytes") or row["cloud_bytes"] or 0))
        runtime_ms = max(0, int(cost.get("runtime_ms") or 0))
        estimated_total = max(
            0.0,
            float(
                cost.get("estimated_total_usd")
                or row["estimated_cost_usd"]
                or compute + storage + transactions
            ),
        )

        summary["document_count"] = int(summary["document_count"]) + 1
        summary["stored_bytes"] = int(summary["stored_bytes"]) + stored_bytes
        summary["runtime_ms"] = int(summary["runtime_ms"]) + runtime_ms
        summary["compute_usd"] = float(summary["compute_usd"]) + compute
        summary["storage_for_retention_usd"] = (
            float(summary["storage_for_retention_usd"]) + storage
        )
        summary["transactions_usd"] = float(summary["transactions_usd"]) + transactions
        summary["estimated_total_usd"] = (
            float(summary["estimated_total_usd"]) + estimated_total
        )
        completed_at = row["completed_at"]
        if completed_at:
            summary["first_completed_at"] = summary["first_completed_at"] or completed_at
            summary["last_completed_at"] = completed_at

    for summary in summaries.values():
        for field in (
            "compute_usd",
            "storage_for_retention_usd",
            "transactions_usd",
            "estimated_total_usd",
        ):
            summary[field] = round(float(summary[field]), 6)
    return summaries


def token_usage_records(
    customer_id: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Return persisted model-call telemetry and completed document coverage."""
    initialize_database()
    with closing(_connect()) as connection:
        if customer_id:
            rows = connection.execute(
                """
                SELECT customer_id, document_id, filename, result_json, completed_at
                FROM document_runs
                WHERE status = 'completed' AND result_json IS NOT NULL
                  AND customer_id = ?
                ORDER BY completed_at DESC, rowid DESC
                """,
                (customer_id,),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT customer_id, document_id, filename, result_json, completed_at
                FROM document_runs
                WHERE status = 'completed' AND result_json IS NOT NULL
                ORDER BY completed_at DESC, rowid DESC
                """
            ).fetchall()

    records: list[dict[str, Any]] = []
    for row in rows:
        try:
            result = json.loads(row["result_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        analyses = result.get("analyses", []) if isinstance(result, dict) else []
        if not isinstance(analyses, list):
            analyses = []
        if not analyses and isinstance(result.get("analysis"), dict):
            analyses = [result["analysis"]]

        for analysis in analyses:
            if not isinstance(analysis, dict) or analysis.get("status") != "completed":
                continue
            performance = analysis.get("performance", {})
            if not isinstance(performance, dict):
                performance = {}
            records.append(
                {
                    "customer_id": str(row["customer_id"]),
                    "document_id": str(row["document_id"]),
                    "filename": str(row["filename"]),
                    "completed_at": row["completed_at"],
                    "model": str(analysis.get("model") or "unknown"),
                    "prompt_tokens": max(0, int(performance.get("prompt_tokens") or 0)),
                    "output_tokens": max(0, int(performance.get("output_tokens") or 0)),
                    "runtime_ms": max(0, int(performance.get("duration_ms") or 0)),
                }
            )
    return records, len(rows)


def get_result_json(document_id: str) -> str | None:
    """Return a stored result JSON document by document ID."""
    initialize_database()
    with closing(_connect()) as connection:
        row = connection.execute(
            "SELECT result_json FROM document_runs WHERE document_id = ?", (document_id,)
        ).fetchone()
    return str(row["result_json"]) if row and row["result_json"] else None


def import_result_files(results_dir: Path) -> int:
    """Backfill existing JSON files into SQLite without replacing newer rows."""
    initialize_database()
    imported = 0
    for result_path in results_dir.glob("*.json"):
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
            document = result["document"]
            processing = result["processing"]
            job_id = str(processing["job_id"])
            document_id = str(document["id"])
            source_path = settings.uploads_dir / f"{document_id}.pdf"
            with closing(_connect()) as connection:
                exists = connection.execute(
                    "SELECT 1 FROM document_runs WHERE job_id = ? OR document_id = ?",
                    (job_id, document_id),
                ).fetchone()
            if exists:
                continue
            create_run(
                job_id=job_id,
                document_id=document_id,
                batch_id=None,
                filename=str(document.get("filename") or result_path.name),
                source_path=source_path,
            )
            complete_run(job_id, result_path, result)
            imported += 1
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return imported