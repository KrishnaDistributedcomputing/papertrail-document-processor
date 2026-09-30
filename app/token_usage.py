"""Aggregate local model token telemetry and runtime-based cost estimates."""

from __future__ import annotations

from typing import Any

from app.config import OLLAMA_MODEL_CATALOG, settings
from app.customers import get_customer


def _compute_cost(runtime_ms: int, hourly_rate: float) -> float:
    return runtime_ms / 3_600_000 * hourly_rate


def _illustrative_azure_cost(prompt_tokens: int, output_tokens: int) -> float:
    return (
        prompt_tokens / 1_000_000 * settings.azure_ai_sample_input_1m_tokens_usd
        + output_tokens / 1_000_000 * settings.azure_ai_sample_output_1m_tokens_usd
    )


def _summary_entry(identifier: str, name: str) -> dict[str, Any]:
    return {
        "id": identifier,
        "name": name,
        "calls": 0,
        "document_ids": set(),
        "prompt_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "runtime_ms": 0,
    }


def _public_summary(summary: dict[str, Any], hourly_rate: float) -> dict[str, Any]:
    calls = int(summary["calls"])
    total_tokens = int(summary["total_tokens"])
    compute_cost = _compute_cost(int(summary["runtime_ms"]), hourly_rate)
    azure_cost = _illustrative_azure_cost(
        int(summary["prompt_tokens"]),
        int(summary["output_tokens"]),
    )
    return {
        "id": summary["id"],
        "name": summary["name"],
        "calls": calls,
        "documents": len(summary["document_ids"]),
        "prompt_tokens": int(summary["prompt_tokens"]),
        "output_tokens": int(summary["output_tokens"]),
        "total_tokens": total_tokens,
        "runtime_ms": int(summary["runtime_ms"]),
        "metered_token_cost_usd": 0.0,
        "illustrative_azure_ai_cost_usd": round(azure_cost, 6),
        "estimated_compute_cost_usd": round(compute_cost, 6),
        "average_tokens_per_call": round(total_tokens / calls) if calls else 0,
        "estimated_compute_per_1k_tokens_usd": round(
            compute_cost / total_tokens * 1000 if total_tokens else 0,
            6,
        ),
    }


def build_token_usage_overview(
    records: list[dict[str, Any]],
    *,
    completed_documents: int,
) -> dict[str, Any]:
    """Build a JSON-compatible token usage and local compute cost overview."""
    hourly_rate = (
        settings.processing_vcpu_hour_usd
        + settings.processing_memory_gb * settings.processing_memory_gb_hour_usd
    )
    models: dict[str, dict[str, Any]] = {}
    customers: dict[str, dict[str, Any]] = {}
    measured_calls = 0
    measured_documents: set[str] = set()
    prompt_tokens = 0
    output_tokens = 0
    runtime_ms = 0
    recent_calls = []

    for record in records:
        model_id = str(record["model"])
        customer_id = str(record["customer_id"])
        customer = get_customer(customer_id)
        model_name = OLLAMA_MODEL_CATALOG.get(model_id, {}).get("name", model_id)
        customer_name = customer.name if customer else customer_id
        model = models.setdefault(model_id, _summary_entry(model_id, str(model_name)))
        customer_summary = customers.setdefault(
            customer_id,
            _summary_entry(customer_id, customer_name),
        )
        total_tokens = int(record["prompt_tokens"]) + int(record["output_tokens"])
        for summary in (model, customer_summary):
            summary["calls"] += 1
            summary["document_ids"].add(record["document_id"])
            summary["prompt_tokens"] += int(record["prompt_tokens"])
            summary["output_tokens"] += int(record["output_tokens"])
            summary["total_tokens"] += total_tokens
            summary["runtime_ms"] += int(record["runtime_ms"])

        if total_tokens:
            measured_calls += 1
            measured_documents.add(str(record["document_id"]))
        prompt_tokens += int(record["prompt_tokens"])
        output_tokens += int(record["output_tokens"])
        runtime_ms += int(record["runtime_ms"])
        call_compute_cost = _compute_cost(int(record["runtime_ms"]), hourly_rate)
        call_azure_cost = _illustrative_azure_cost(
            int(record["prompt_tokens"]),
            int(record["output_tokens"]),
        )
        recent_calls.append(
            {
                **record,
                "customer_name": customer_name,
                "model_name": model_name,
                "total_tokens": total_tokens,
                "metered_token_cost_usd": 0.0,
                "illustrative_azure_ai_cost_usd": round(call_azure_cost, 6),
                "estimated_compute_cost_usd": round(call_compute_cost, 6),
            }
        )

    total_tokens = prompt_tokens + output_tokens
    total_compute_cost = _compute_cost(runtime_ms, hourly_rate)
    total_azure_cost = _illustrative_azure_cost(prompt_tokens, output_tokens)
    public_models = sorted(
        (_public_summary(summary, hourly_rate) for summary in models.values()),
        key=lambda summary: summary["total_tokens"],
        reverse=True,
    )
    public_customers = sorted(
        (_public_summary(summary, hourly_rate) for summary in customers.values()),
        key=lambda summary: summary["total_tokens"],
        reverse=True,
    )
    return {
        "scope": "all_completed_documents",
        "currency": "USD",
        "provider": "Ollama",
        "billing_model": "local_runtime",
        "totals": {
            "completed_documents": completed_documents,
            "documents_with_token_telemetry": len(measured_documents),
            "model_calls": len(records),
            "calls_with_token_telemetry": measured_calls,
            "prompt_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "runtime_ms": runtime_ms,
            "metered_token_cost_usd": 0.0,
            "illustrative_azure_ai_cost_usd": round(total_azure_cost, 6),
            "estimated_compute_cost_usd": round(total_compute_cost, 6),
            "average_tokens_per_call": round(total_tokens / len(records)) if records else 0,
            "estimated_compute_per_1k_tokens_usd": round(
                total_compute_cost / total_tokens * 1000 if total_tokens else 0,
                6,
            ),
        },
        "pricing": {
            "input_1m_tokens_usd": 0.0,
            "output_1m_tokens_usd": 0.0,
            "azure_sample_input_1m_tokens_usd": settings.azure_ai_sample_input_1m_tokens_usd,
            "azure_sample_output_1m_tokens_usd": settings.azure_ai_sample_output_1m_tokens_usd,
            "vcpu_hour_usd": settings.processing_vcpu_hour_usd,
            "memory_gb_hour_usd": settings.processing_memory_gb_hour_usd,
            "memory_gb": settings.processing_memory_gb,
            "effective_compute_hour_usd": round(hourly_rate, 6),
        },
        "models": public_models,
        "customers": public_customers,
        "recent_calls": recent_calls[:25],
        "methodology": {
            "token_charge": "Local Ollama models have no metered per-token API charge.",
            "azure_sample": "Illustrative Azure AI cost applies configurable sample input and output rates to recorded tokens; it is not billed usage or a live Azure retail quote.",
            "compute_cost": "Recorded model runtime multiplied by the configured vCPU and memory hourly rates.",
            "cost_boundary": "This is operational compute attribution, not an additional charge to add to Azure Cost Management or the processing dashboard.",
            "coverage": "Only completed model calls with persisted Ollama telemetry are counted.",
        },
    }