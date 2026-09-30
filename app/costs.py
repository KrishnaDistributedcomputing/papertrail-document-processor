"""Estimate processing and Azure Blob costs from configured retail rates."""

from __future__ import annotations

from typing import Any

from app.config import settings

GIB = 1024**3
AVERAGE_DAYS_PER_MONTH = 365.25 / 12


def estimate_document_cost(
    result: dict[str, Any],
    *,
    result_size_bytes: int,
    retention_days: int,
) -> dict[str, Any]:
    """Return a transparent per-document cost estimate in US dollars."""
    source_size_bytes = max(0, int(result.get("document", {}).get("size_bytes") or 0))
    stored_bytes = source_size_bytes + max(0, result_size_bytes)
    processing_ms = max(0, int(result.get("processing", {}).get("duration_ms") or 0))
    analysis_ms = sum(
        max(0, int(analysis.get("performance", {}).get("duration_ms") or 0))
        for analysis in result.get("analyses", [])
        if isinstance(analysis, dict)
    )
    runtime_hours = (processing_ms + analysis_ms) / 3_600_000
    compute_hourly_rate = (
        settings.processing_vcpu_hour_usd
        + settings.processing_memory_gb * settings.processing_memory_gb_hour_usd
    )
    compute_cost = runtime_hours * compute_hourly_rate
    monthly_storage_cost = stored_bytes / GIB * settings.azure_storage_gb_month_usd
    retained_storage_cost = monthly_storage_cost * retention_days / AVERAGE_DAYS_PER_MONTH
    write_cost = 2 / 10_000 * settings.azure_write_10k_usd
    lifecycle_delete_cost = 2 / 10_000 * settings.azure_other_10k_usd
    transaction_cost = write_cost + lifecycle_delete_cost
    rounded_compute = round(compute_cost, 6)
    rounded_storage = round(retained_storage_cost, 6)
    rounded_monthly_storage = round(monthly_storage_cost, 6)
    rounded_transactions = round(transaction_cost, 6)
    total_cost = rounded_compute + rounded_storage + rounded_transactions

    return {
        "currency": "USD",
        "estimated_total_usd": round(total_cost, 6),
        "compute_usd": rounded_compute,
        "storage_for_retention_usd": rounded_storage,
        "storage_monthly_usd": rounded_monthly_storage,
        "transactions_usd": rounded_transactions,
        "retention_days": retention_days,
        "stored_bytes": stored_bytes,
        "runtime_ms": processing_ms + analysis_ms,
        "pricing": {
            "region": settings.azure_storage_region,
            "storage_sku": settings.azure_storage_sku,
            "storage_gb_month_usd": settings.azure_storage_gb_month_usd,
            "write_10k_usd": settings.azure_write_10k_usd,
            "other_10k_usd": settings.azure_other_10k_usd,
            "vcpu_hour_usd": settings.processing_vcpu_hour_usd,
            "memory_gb_hour_usd": settings.processing_memory_gb_hour_usd,
            "memory_gb": settings.processing_memory_gb,
        },
        "disclaimer": "Estimate from configured retail rates; use Azure Cost Management for billed cost.",
    }