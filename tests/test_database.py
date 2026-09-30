"""Tests for persistent document run history."""

import json
from pathlib import Path
from unittest.mock import patch

from app import database
from app.config import settings
from app.main import get_history, get_job, get_result


def _result() -> dict[str, object]:
    return {
        "schema_version": "1.2",
        "document": {
            "id": "document-1",
            "filename": "report.pdf",
            "page_count": 1,
            "size_bytes": 120,
            "sha256": "abc123",
            "classification": {"category": "report"},
        },
        "processing": {
            "job_id": "job-1",
            "status": "completed",
            "warnings": [],
        },
        "analysis": {"status": "completed", "model": "qwen2.5:1.5b"},
        "pages": [{"text_source": "native"}],
    }


def test_persists_run_state_and_result_json(tmp_path: Path) -> None:
    with patch.object(settings, "data_dir", tmp_path):
        source_path = settings.uploads_dir / "document-1.pdf"
        database.create_run(
            job_id="job-1",
            document_id="document-1",
            batch_id="batch-1",
            customer_id="apple",
            filename="report.pdf",
            source_path=source_path,
        )
        database.update_run(
            "job-1",
            status="processing",
            stage="analyzing",
            progress=97,
        )
        database.complete_run("job-1", settings.results_dir / "document-1.json", _result())

        run = database.get_run("job-1")
        stored_result = json.loads(database.get_result_json("document-1") or "{}")

    assert run is not None
    assert run["status"] == "completed"
    assert run["customer_id"] == "apple"
    assert run["progress"] == 100
    assert run["category"] == "report"
    assert run["text_sources"] == ["native"]
    assert run["analysis_model"] == "qwen2.5:1.5b"
    assert stored_result["schema_version"] == "1.2"


def test_filters_history_and_updates_customer_retention(tmp_path: Path) -> None:
    with patch.object(settings, "data_dir", tmp_path):
        for index, customer_id in enumerate(("apple", "microsoft"), start=1):
            database.create_run(
                job_id=f"job-{index}",
                document_id=f"document-{index}",
                batch_id=None,
                customer_id=customer_id,
                filename=f"{customer_id}.pdf",
                source_path=settings.uploads_dir / f"document-{index}.pdf",
            )

        apple_runs, apple_total = database.list_runs(customer_id="apple")
        retention_days = database.set_customer_retention("apple", 180)
        stored_retention_days = database.get_customer_retention("apple")

    assert apple_total == 1
    assert apple_runs[0]["customer_id"] == "apple"
    assert retention_days == 180
    assert stored_retention_days == 180


def test_imports_existing_result_files_once(tmp_path: Path) -> None:
    with patch.object(settings, "data_dir", tmp_path):
        settings.results_dir.mkdir(parents=True)
        result_path = settings.results_dir / "document-1.json"
        result_path.write_text(json.dumps(_result()), encoding="utf-8")

        first_import = database.import_result_files(settings.results_dir)
        second_import = database.import_result_files(settings.results_dir)
        runs, total = database.list_runs()

    assert first_import == 1
    assert second_import == 0
    assert total == 1
    assert runs[0]["filename"] == "report.pdf"


def test_api_recovers_status_and_result_from_sqlite(tmp_path: Path) -> None:
    with patch.object(settings, "data_dir", tmp_path):
        database.create_run(
            job_id="job-1",
            document_id="document-1",
            batch_id="batch-1",
            filename="report.pdf",
            source_path=settings.uploads_dir / "document-1.pdf",
        )
        database.complete_run("job-1", settings.results_dir / "missing.json", _result())

        job = get_job("job-1")
        history = get_history()
        result = get_result("document-1")

    assert job == {
        "job_id": "job-1",
        "document_id": "document-1",
        "filename": "report.pdf",
        "status": "completed",
        "stage": "completed",
        "progress": 100,
    }
    assert history["total"] == 1
    assert history["runs"][0]["result_available"] is True
    assert result["document"]["filename"] == "report.pdf"