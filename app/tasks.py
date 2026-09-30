"""Celery tasks for asynchronous PDF processing."""

import json
from pathlib import Path
from typing import Any

from celery import Celery

from app import cloud_storage, database
from app.analysis import AnalysisError, analyze_document
from app.config import settings
from app.costs import estimate_document_cost
from app.customers import get_customer
from app.processor import process_pdf

celery_app = Celery("papertrail", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_track_started=True,
    task_time_limit=settings.job_timeout_seconds,
    result_expires=86400,
    worker_prefetch_multiplier=1,
)


@celery_app.task(bind=True, name="app.tasks.process_document")
def process_document(
    self: Any,
    source_path: str,
    document_id: str,
    original_filename: str,
    models: list[str] | None = None,
    customer_id: str = "microsoft",
) -> dict[str, Any]:
    """Process one stored PDF and persist its JSON result."""
    job_id = str(self.request.id)
    result_path = settings.results_dir / f"{document_id}.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)

    def update_progress(stage: str, percent: int) -> None:
        self.update_state(state="PROGRESS", meta={"stage": stage, "progress": percent})
        database.update_run(
            job_id,
            status="processing",
            stage=stage,
            progress=percent,
        )

    try:
        update_progress("starting", 1)
        result = process_pdf(
            Path(source_path),
            document_id,
            job_id,
            original_filename,
            min_native_chars=settings.native_text_min_chars,
            ocr_dpi=settings.ocr_dpi,
            ocr_languages=settings.ocr_languages,
            progress=update_progress,
        )
        customer = get_customer(customer_id)
        if customer is None:
            raise ValueError(f"Unknown customer: {customer_id}")
        result["document"]["customer"] = {
            "id": customer.id,
            "name": customer.name,
            "container": customer.container,
        }
        if settings.ai_enabled:
            selected_models = models or [settings.ollama_model]
            analyses: list[dict[str, Any]] = []
            for index, model in enumerate(selected_models):
                update_progress("analyzing", min(97 + index, 99))
                try:
                    analyses.append(
                        analyze_document(
                            result,
                            base_url=settings.ollama_url,
                            model=model,
                            timeout_seconds=settings.ai_timeout_seconds,
                            max_characters=settings.ai_max_characters,
                        )
                    )
                except AnalysisError as error:
                    analyses.append(
                        {
                            "status": "failed",
                            "provider": "ollama",
                            "model": model,
                            "reason": str(error),
                        }
                    )
                    result["processing"]["status"] = "completed_with_warnings"
                    result["processing"]["warnings"].append(
                        {
                            "code": "AI_ANALYSIS_FAILED",
                            "message": f"{model}: {error}",
                        }
                    )
            result["analyses"] = analyses
            result["analysis"] = analyses[0]
        else:
            result["analysis"] = {"status": "disabled"}
            result["analyses"] = []
        retention_days = database.get_customer_retention(customer_id)
        storage = cloud_storage.planned_location(customer, document_id, retention_days)
        if cloud_storage.is_configured():
            storage["status"] = "stored"
        result["storage"] = storage
        provisional_json = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
        result["cost_estimate"] = estimate_document_cost(
            result,
            result_size_bytes=len(provisional_json),
            retention_days=retention_days,
        )
        result_json = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
        if cloud_storage.is_configured():
            update_progress("storing", 99)
            try:
                result["storage"] = cloud_storage.upload_document(
                    customer=customer,
                    document_id=document_id,
                    source_path=Path(source_path),
                    result_json=result_json,
                    retention_days=retention_days,
                    location=storage,
                )
            except cloud_storage.CloudStorageError as error:
                result["storage"] = {**storage, "status": "failed", "reason": str(error)}
                result["processing"]["status"] = "completed_with_warnings"
                result["processing"]["warnings"].append(
                    {"code": "AZURE_STORAGE_FAILED", "message": str(error)}
                )
            result_json = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
        temporary_path = result_path.with_suffix(".tmp")
        temporary_path.write_bytes(result_json)
        temporary_path.replace(result_path)
        database.complete_run(job_id, result_path, result)
        return {"document_id": document_id, "result_path": str(result_path)}
    except Exception as error:
        database.fail_run(job_id, f"{type(error).__name__}: {error}")
        raise