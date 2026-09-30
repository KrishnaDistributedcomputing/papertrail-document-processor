"""Tests for document upload API behavior."""

import asyncio
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pymupdf
import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from app import database
from app.config import settings
from app.main import (
    RetentionUpdate,
    get_cost_overview,
    get_customers,
    get_models,
    get_storage_overview,
    update_customer_retention,
    upload_documents,
)


def _pdf_bytes(text: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    payload = document.tobytes()
    document.close()
    return payload


def test_uploads_multiple_documents_as_independent_jobs(tmp_path: Path) -> None:
    files = [
        UploadFile(BytesIO(_pdf_bytes("First report")), filename="first.pdf"),
        UploadFile(BytesIO(_pdf_bytes("Second invoice")), filename="second.pdf"),
    ]

    with (
        patch.object(settings, "data_dir", tmp_path),
        patch("app.main.process_document.apply_async") as apply_async,
    ):
        result = asyncio.run(
            upload_documents(
                files,
                models=["qwen2.5:1.5b", "qwen2.5:0.5b"],
                customer_id="apple",
            )
        )
        runs, total = database.list_runs()

    assert result["status"] == "queued"
    assert [item["filename"] for item in result["documents"]] == ["first.pdf", "second.pdf"]
    assert len({item["job_id"] for item in result["documents"]}) == 2
    assert len(list((tmp_path / "uploads").glob("*.pdf"))) == 2
    assert apply_async.call_count == 2
    assert result["models"] == ["qwen2.5:1.5b", "qwen2.5:0.5b"]
    assert result["customer_id"] == "apple"
    assert [call.kwargs["args"][3] for call in apply_async.call_args_list] == [
        ["qwen2.5:1.5b", "qwen2.5:0.5b"],
        ["qwen2.5:1.5b", "qwen2.5:0.5b"],
    ]
    assert [call.kwargs["args"][4] for call in apply_async.call_args_list] == [
        "apple",
        "apple",
    ]
    assert [call.kwargs["task_id"] for call in apply_async.call_args_list] == [
        item["job_id"] for item in result["documents"]
    ]
    assert total == 2
    assert {run["filename"] for run in runs} == {"first.pdf", "second.pdf"}
    assert {run["batch_id"] for run in runs} == {result["batch_id"]}
    assert {run["status"] for run in runs} == {"queued"}


def test_lists_configured_analysis_models() -> None:
    payload = get_models()

    assert payload["max_selected"] == 2
    assert [model["id"] for model in payload["models"]] == [
        "qwen2.5:1.5b",
        "qwen2.5:0.5b",
    ]
    assert payload["models"][0]["default"] is True


def test_rejects_unsupported_analysis_model_before_staging() -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(upload_documents([], models=["remote-model:latest"]))

    assert error.value.status_code == 422
    assert error.value.detail == "Unsupported analysis model: remote-model:latest."


def test_lists_customers_and_updates_retention(tmp_path: Path) -> None:
    with patch.object(settings, "data_dir", tmp_path):
        payload = get_customers()
        updated = update_customer_retention(
            "nvidia",
            RetentionUpdate(retention_days=365),
        )

    assert len(payload["customers"]) == 10
    assert payload["customers"][0]["container"] == "cust-apple"
    assert updated == {
        "customer_id": "nvidia",
        "retention_days": 365,
        "retention_policy": "azure_lifecycle_management",
        "policy_rule": "papertrail-nvidia-retention",
        "cloud_status": "not_configured",
        "rules_updated": 0,
    }


def test_returns_storage_topology_without_cloud_credentials(tmp_path: Path) -> None:
    with patch.object(settings, "data_dir", tmp_path):
        payload = get_storage_overview()

    assert payload["storage"]["status"] == "not_configured"
    assert payload["totals"]["customers"] == 10
    assert len(payload["customers"]) == 10
    assert payload["customers"][0]["container"] == "cust-apple"


def test_returns_customer_cost_breakdown(tmp_path: Path) -> None:
    result = {
        "document": {"size_bytes": 1024},
        "processing": {"status": "completed", "warnings": []},
        "analysis": {},
        "pages": [],
        "storage": {"status": "planned"},
        "cost_estimate": {
            "compute_usd": 0.003,
            "storage_for_retention_usd": 0.002,
            "transactions_usd": 0.001,
            "estimated_total_usd": 0.006,
            "stored_bytes": 512 * 1024 * 1024,
            "runtime_ms": 4000,
        },
    }

    with patch.object(settings, "data_dir", tmp_path):
        database.create_run(
            job_id="cost-job",
            document_id="cost-document",
            batch_id=None,
            customer_id="apple",
            filename="cost.pdf",
            source_path=tmp_path / "cost.pdf",
        )
        database.complete_run("cost-job", tmp_path / "cost.json", result)
        payload = get_cost_overview()

    apple = next(customer for customer in payload["customers"] if customer["id"] == "apple")
    assert payload["scope"] == "all_completed_documents"
    assert payload["totals"]["documents"] == 1
    assert payload["totals"]["estimated_total_usd"] == 0.006
    assert apple["document_count"] == 1
    assert apple["compute_usd"] == 0.003
    assert apple["storage_for_retention_usd"] == 0.002
    assert apple["transactions_usd"] == 0.001
    assert apple["monthly_storage_cost_usd"] > 0
    assert payload["totals"]["monthly_storage_cost_usd"] == apple["monthly_storage_cost_usd"]
    assert apple["cost_per_document_usd"] == 0.006
    assert apple["cost_share_percent"] == 100.0


def test_rejects_unsupported_customer_before_staging() -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(upload_documents([], customer_id="unknown-customer"))

    assert error.value.status_code == 422
    assert error.value.detail == "Unsupported customer: unknown-customer."