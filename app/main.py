"""FastAPI application for uploading PDFs and retrieving structured results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

import pymupdf
from celery.result import AsyncResult
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import cloud_storage, database
from app.config import OLLAMA_MODEL_CATALOG, settings
from app.customers import CUSTOMERS, get_customer, list_customers
from app.support import answer_support_question
from app.tasks import celery_app, process_document
from app.token_usage import build_token_usage_overview

app = FastAPI(title="Papertrail", version="1.6.0")

StagedDocument = tuple[str, Path, str]


class RetentionUpdate(BaseModel):
    """Validate a customer retention policy update."""

    retention_days: int = Field(ge=1, le=3650)


class SupportQuestion(BaseModel):
    """Validate one Level 1 support question."""

    question: str = Field(min_length=1, max_length=500)


def _select_models(requested_models: list[str] | None) -> list[str]:
    selected = list(dict.fromkeys(requested_models or [settings.ollama_model]))
    available = set(settings.available_ollama_models)
    unsupported = [model for model in selected if model not in available]
    if unsupported:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported analysis model: {', '.join(unsupported)}.",
        )
    if not selected:
        raise HTTPException(status_code=422, detail="Choose at least one analysis model.")
    if len(selected) > settings.max_analysis_models:
        raise HTTPException(
            status_code=422,
            detail=f"Choose at most {settings.max_analysis_models} analysis models.",
        )
    return selected


def _select_customer(customer_id: str) -> str:
    if get_customer(customer_id) is None:
        raise HTTPException(status_code=422, detail=f"Unsupported customer: {customer_id}.")
    return customer_id


def _job_payload(job: AsyncResult[Any]) -> dict[str, Any]:
    state = job.state
    if state == "PENDING":
        return {"status": "queued", "stage": "queued", "progress": 0}
    if state == "STARTED":
        return {"status": "processing", "stage": "starting", "progress": 1}
    if state == "PROGRESS":
        details = job.info if isinstance(job.info, dict) else {}
        return {
            "status": "processing",
            "stage": details.get("stage", "processing"),
            "progress": details.get("progress", 0),
        }
    if state == "SUCCESS":
        return {"status": "completed", "stage": "completed", "progress": 100, **job.result}
    if state == "REVOKED":
        return {"status": "cancelled", "stage": "cancelled", "progress": 0}
    return {
        "status": "failed",
        "stage": "failed",
        "progress": 0,
        "error": "Document processing failed. Check the worker logs for the request ID.",
    }


@app.on_event("startup")
def create_data_directories() -> None:
    """Create persistent data directories before accepting uploads."""
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.results_dir.mkdir(parents=True, exist_ok=True)
    database.initialize_database()
    database.import_result_files(settings.results_dir)


async def _stage_document(file: UploadFile) -> StagedDocument:
    """Validate and store one PDF before it is queued."""
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    document_id = str(uuid4())
    source_path = settings.uploads_dir / f"{document_id}.pdf"
    size = 0
    first_chunk = True

    try:
        with source_path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                if first_chunk and not chunk.startswith(b"%PDF-"):
                    raise HTTPException(status_code=415, detail="The selected file is not a valid PDF.")
                first_chunk = False
                size += len(chunk)
                if size > settings.max_file_size_mb * 1024 * 1024:
                    raise HTTPException(
                        status_code=413,
                        detail=f"The PDF exceeds the {settings.max_file_size_mb} MB limit.",
                    )
                output.write(chunk)

        if size == 0:
            raise HTTPException(status_code=400, detail="The uploaded file is empty.")
        try:
            with pymupdf.open(source_path) as document:
                if document.needs_pass:
                    raise HTTPException(status_code=422, detail="Encrypted PDFs are not supported.")
                if document.page_count > settings.max_pdf_pages:
                    raise HTTPException(
                        status_code=422,
                        detail=f"The PDF exceeds the {settings.max_pdf_pages}-page limit.",
                    )
        except pymupdf.FileDataError as error:
            raise HTTPException(status_code=422, detail="The PDF is malformed.") from error

        display_name = Path(file.filename or "document.pdf").name
        return document_id, source_path, display_name
    except Exception:
        source_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


def _queue_document(
    staged: StagedDocument,
    batch_id: str,
    selected_models: list[str],
    customer_id: str,
) -> dict[str, Any]:
    document_id, source_path, display_name = staged
    job_id = str(uuid4())
    database.create_run(
        job_id=job_id,
        document_id=document_id,
        batch_id=batch_id,
        customer_id=customer_id,
        filename=display_name,
        source_path=source_path,
    )
    try:
        process_document.apply_async(
            args=(str(source_path), document_id, display_name, selected_models, customer_id),
            task_id=job_id,
        )
    except Exception as error:
        database.fail_run(job_id, f"{type(error).__name__}: {error}")
        raise HTTPException(status_code=503, detail="The document could not be queued.") from error
    return {
        "document_id": document_id,
        "filename": display_name,
        "job_id": job_id,
        "status": "queued",
        "customer_id": customer_id,
        "models": selected_models,
        "status_url": f"/api/v1/jobs/{job_id}",
    }


@app.get("/api/v1/models")
def get_models() -> dict[str, Any]:
    """Return locally installed analysis models available for selection."""
    models = []
    for model_id in settings.available_ollama_models:
        details = OLLAMA_MODEL_CATALOG.get(
            model_id,
            {"name": model_id, "description": "Configured local Ollama model", "size": "Local"},
        )
        models.append(
            {
                "id": model_id,
                **details,
                "default": model_id == settings.ollama_model,
            }
        )
    return {
        "enabled": settings.ai_enabled,
        "models": models,
        "max_selected": settings.max_analysis_models,
    }


@app.post("/api/v1/support/chat")
def ask_support(question: SupportQuestion) -> dict[str, object]:
    """Answer a Level 1 question about the Papertrail portal."""
    if not question.question.strip():
        raise HTTPException(status_code=422, detail="Enter a portal question.")
    return answer_support_question(question.question)


@app.get("/api/v1/customers")
def get_customers() -> dict[str, Any]:
    """Return sample customer tenants and their retention settings."""
    retention = database.list_customer_settings()
    return {
        "customers": [
            {
                **customer,
                "retention_days": retention[customer["id"]],
            }
            for customer in list_customers()
        ]
    }


@app.patch("/api/v1/customers/{customer_id}/retention")
def update_customer_retention(
    customer_id: str,
    update: RetentionUpdate,
) -> dict[str, Any]:
    """Update the document retention period for one customer."""
    customer = get_customer(_select_customer(customer_id))
    assert customer is not None
    retention_days = database.set_customer_retention(customer_id, update.retention_days)
    policy_rule = cloud_storage.build_retention_rule(customer, retention_days)["name"]
    rules_updated = 0
    cloud_status = (
        "management_identity_required"
        if settings.azure_storage_account_name
        else "not_configured"
    )
    warning = None
    if cloud_storage.is_management_configured():
        try:
            rules_updated = cloud_storage.sync_retention_policies(
                database.list_customer_settings()
            )
            cloud_status = "updated"
        except cloud_storage.CloudStorageError as error:
            cloud_status = "failed"
            warning = str(error)
    return {
        "customer_id": customer_id,
        "retention_days": retention_days,
        "retention_policy": "azure_lifecycle_management",
        "policy_rule": policy_rule,
        "cloud_status": cloud_status,
        "rules_updated": rules_updated,
        **({"warning": warning} if warning else {}),
    }


@app.get("/api/v1/storage/overview")
def get_storage_overview() -> dict[str, Any]:
    """Return the customer Blob topology, live usage, and estimated costs."""
    retention = database.list_customer_settings()
    summaries = database.customer_run_summaries()
    customers = []
    warnings = []
    total_bytes = 0
    total_blobs = 0
    total_documents = 0
    total_estimated_cost = 0.0

    for customer in CUSTOMERS:
        summary = summaries.get(
            customer.id,
            {
                "document_count": 0,
                "source_bytes": 0,
                "cloud_bytes": 0,
                "estimated_cost_usd": 0.0,
            },
        )
        usage = {
            "blob_count": int(summary["document_count"]) * 2,
            "source_count": int(summary["document_count"]),
            "result_count": int(summary["document_count"]),
            "bytes": int(summary["cloud_bytes"]),
        }
        inventory_status = "local_estimate"
        if cloud_storage.is_configured():
            try:
                usage = cloud_storage.container_usage(customer)
                inventory_status = "live"
            except cloud_storage.CloudStorageError as error:
                inventory_status = "unavailable"
                warnings.append(f"{customer.name}: {error}")
        monthly_storage_cost = (
            usage["bytes"] / (1024**3) * settings.azure_storage_gb_month_usd
        )
        customers.append(
            {
                **customer.to_dict(),
                "retention_days": retention[customer.id],
                "inventory_status": inventory_status,
                **usage,
                "monthly_storage_cost_usd": round(monthly_storage_cost, 6),
                "estimated_processing_cost_usd": summary["estimated_cost_usd"],
                "document_count": summary["document_count"],
            }
        )
        total_bytes += usage["bytes"]
        total_blobs += usage["blob_count"]
        total_documents += int(summary["document_count"])
        total_estimated_cost += float(summary["estimated_cost_usd"])

    return {
        "storage": {
            "provider": "Azure Blob Storage",
            "configured": cloud_storage.is_configured(),
            "status": "degraded" if warnings else "connected" if cloud_storage.is_configured() else "not_configured",
            "account": settings.azure_storage_account_name,
            "region": settings.azure_storage_region,
            "sku": settings.azure_storage_sku,
            "hierarchical_namespace": True,
            "retention_policy": "Azure lifecycle management",
            "retention_management_configured": cloud_storage.is_management_configured(),
        },
        "totals": {
            "customers": len(customers),
            "documents": total_documents,
            "blobs": total_blobs,
            "bytes": total_bytes,
            "monthly_storage_cost_usd": round(
                total_bytes / (1024**3) * settings.azure_storage_gb_month_usd,
                6,
            ),
            "estimated_processing_cost_usd": round(total_estimated_cost, 6),
        },
        "pricing": {
            "currency": "USD",
            "storage_gb_month_usd": settings.azure_storage_gb_month_usd,
            "write_10k_usd": settings.azure_write_10k_usd,
            "read_10k_usd": settings.azure_read_10k_usd,
            "other_10k_usd": settings.azure_other_10k_usd,
            "source": "Configured Azure retail rate assumptions",
        },
        "customers": customers,
        "warnings": warnings,
    }


@app.get("/api/v1/costs/overview")
def get_cost_overview() -> dict[str, Any]:
    """Return estimated processing and storage costs by customer."""
    summaries = database.customer_cost_summaries()
    customers = []
    warnings = []
    totals = {
        "documents": 0,
        "stored_bytes": 0,
        "runtime_ms": 0,
        "compute_usd": 0.0,
        "storage_for_retention_usd": 0.0,
        "transactions_usd": 0.0,
        "estimated_total_usd": 0.0,
        "monthly_storage_cost_usd": 0.0,
    }

    for customer in CUSTOMERS:
        summary = summaries.get(
            customer.id,
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
        storage_bytes = int(summary["stored_bytes"])
        inventory_status = "local_estimate"
        if cloud_storage.is_configured():
            try:
                usage = cloud_storage.container_usage(customer)
                storage_bytes = int(usage["bytes"])
                inventory_status = "live"
            except cloud_storage.CloudStorageError as error:
                inventory_status = "unavailable"
                warnings.append(f"{customer.name}: {error}")
        monthly_storage_cost = (
            storage_bytes / (1024**3) * settings.azure_storage_gb_month_usd
        )
        rounded_monthly_storage_cost = round(monthly_storage_cost, 6)
        document_count = int(summary["document_count"])
        estimated_total = float(summary["estimated_total_usd"])
        customers.append(
            {
                **customer.to_dict(),
                **summary,
                "storage_bytes": storage_bytes,
                "inventory_status": inventory_status,
                "monthly_storage_cost_usd": rounded_monthly_storage_cost,
                "cost_per_document_usd": round(
                    estimated_total / document_count if document_count else 0,
                    6,
                ),
            }
        )
        totals["documents"] += document_count
        totals["stored_bytes"] += storage_bytes
        totals["runtime_ms"] += int(summary["runtime_ms"])
        for field in (
            "compute_usd",
            "storage_for_retention_usd",
            "transactions_usd",
            "estimated_total_usd",
        ):
            totals[field] += float(summary[field])
        totals["monthly_storage_cost_usd"] += rounded_monthly_storage_cost

    estimated_total = totals["estimated_total_usd"]
    for customer in customers:
        customer["cost_share_percent"] = round(
            float(customer["estimated_total_usd"]) / estimated_total * 100
            if estimated_total
            else 0,
            1,
        )
    for field in (
        "compute_usd",
        "storage_for_retention_usd",
        "transactions_usd",
        "estimated_total_usd",
        "monthly_storage_cost_usd",
    ):
        totals[field] = round(float(totals[field]), 6)

    return {
        "scope": "all_completed_documents",
        "currency": "USD",
        "totals": totals,
        "customers": customers,
        "pricing": {
            "region": settings.azure_storage_region,
            "storage_sku": settings.azure_storage_sku,
            "storage_gb_month_usd": settings.azure_storage_gb_month_usd,
            "source": "Configured Azure retail rate assumptions",
        },
        "methodology": {
            "processing": "Measured runtime multiplied by configured vCPU and memory rates.",
            "retention_storage": "Stored bytes projected across the lifecycle duration active when each document was processed.",
            "monthly_storage": "Current Azure container bytes multiplied by the configured GB-month rate; local bytes are used when live inventory is unavailable.",
            "billing_source": "Azure Cost Management remains the source of billed charges.",
        },
        "warnings": warnings,
    }


@app.get("/api/v1/tokens/overview")
def get_token_usage_overview(customer_id: str | None = None) -> dict[str, Any]:
    """Return local model token telemetry and attributed compute cost."""
    if customer_id is not None:
        _select_customer(customer_id)
    records, completed_documents = database.token_usage_records(customer_id)
    overview = build_token_usage_overview(
        records,
        completed_documents=completed_documents,
    )
    if customer_id:
        overview["scope"] = "customer"
        overview["customer_id"] = customer_id
    return overview


@app.post("/api/v1/documents", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    file: Annotated[UploadFile, File(...)],
    models: Annotated[list[str] | None, Form()] = None,
    customer_id: Annotated[str, Form()] = "microsoft",
) -> dict[str, Any]:
    """Validate, store, and queue one PDF document."""
    selected_models = _select_models(models)
    selected_customer = _select_customer(customer_id)
    return _queue_document(
        await _stage_document(file),
        str(uuid4()),
        selected_models,
        selected_customer,
    )


@app.post("/api/v1/documents/batch", status_code=status.HTTP_202_ACCEPTED)
async def upload_documents(
    files: Annotated[list[UploadFile], File(...)],
    models: Annotated[list[str] | None, Form()] = None,
    customer_id: Annotated[str, Form()] = "microsoft",
) -> dict[str, Any]:
    """Validate and queue a bounded batch of PDF documents."""
    selected_models = _select_models(models)
    selected_customer = _select_customer(customer_id)
    if not files:
        raise HTTPException(status_code=400, detail="Choose at least one PDF document.")
    if len(files) > settings.max_batch_documents:
        raise HTTPException(
            status_code=413,
            detail=f"A batch can contain at most {settings.max_batch_documents} documents.",
        )

    staged_documents: list[StagedDocument] = []
    try:
        for file in files:
            staged_documents.append(await _stage_document(file))
    except Exception:
        for _, source_path, _ in staged_documents:
            source_path.unlink(missing_ok=True)
        raise

    batch_id = str(uuid4())
    return {
        "batch_id": batch_id,
        "status": "queued",
        "customer_id": selected_customer,
        "models": selected_models,
        "documents": [
            _queue_document(staged, batch_id, selected_models, selected_customer)
            for staged in staged_documents
        ],
    }


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    """Return current processing status for a job."""
    durable_run = database.get_run(job_id)
    if durable_run:
        return {
            "job_id": job_id,
            "document_id": durable_run["document_id"],
            "filename": durable_run["filename"],
            "status": durable_run["status"],
            "stage": durable_run["stage"],
            "progress": durable_run["progress"],
            **({"error": durable_run["error"]} if durable_run["error"] else {}),
        }
    return {"job_id": job_id, **_job_payload(AsyncResult(job_id, app=celery_app))}


@app.delete("/api/v1/jobs/{job_id}", status_code=status.HTTP_202_ACCEPTED)
def cancel_job(job_id: str) -> dict[str, str]:
    """Cancel a queued processing job."""
    celery_app.control.revoke(job_id, terminate=False)
    if database.get_run(job_id):
        database.cancel_run(job_id)
    return {"job_id": job_id, "status": "cancelled"}


@app.get("/api/v1/history")
def get_history(
    limit: int = 20,
    offset: int = 0,
    customer_id: str | None = None,
) -> dict[str, Any]:
    """Return recent processing runs from durable local storage."""
    if customer_id is not None:
        _select_customer(customer_id)
    runs, total = database.list_runs(
        limit=limit,
        offset=offset,
        customer_id=customer_id,
    )
    return {"runs": runs, "total": total, "limit": max(1, min(limit, 100)), "offset": max(0, offset)}


@app.get("/api/v1/documents/{document_id}/result")
def get_result(document_id: str) -> dict[str, Any]:
    """Return a completed document result."""
    result_path = settings.results_dir / f"{document_id}.json"
    if result_path.exists():
        return json.loads(result_path.read_text(encoding="utf-8"))
    result_json = database.get_result_json(document_id)
    if result_json:
        return json.loads(result_json)
    raise HTTPException(status_code=404, detail="The result is not available.")


@app.get("/api/v1/documents/{document_id}/download")
def download_result(document_id: str) -> Response:
    """Download a completed document result as JSON."""
    result_path = settings.results_dir / f"{document_id}.json"
    if result_path.exists():
        return FileResponse(
            result_path,
            media_type="application/json",
            filename=f"{document_id}.json",
        )
    result_json = database.get_result_json(document_id)
    if result_json:
        return Response(
            result_json,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{document_id}.json"'},
        )
    raise HTTPException(status_code=404, detail="The result is not available.")


@app.get("/api/v1/health/live")
def liveness() -> dict[str, str]:
    """Report process liveness."""
    return {"status": "ok"}


app.mount("/", StaticFiles(directory="web", html=True), name="web")