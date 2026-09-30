"""Tests for document processing cost estimates."""

from app.costs import estimate_document_cost


def test_estimates_compute_storage_and_transaction_costs() -> None:
    result = {
        "document": {"size_bytes": 10 * 1024 * 1024},
        "processing": {"duration_ms": 30_000},
        "analyses": [
            {"performance": {"duration_ms": 20_000}},
            {"performance": {"duration_ms": 10_000}},
        ],
    }

    estimate = estimate_document_cost(
        result,
        result_size_bytes=1024 * 1024,
        retention_days=90,
    )

    assert estimate["currency"] == "USD"
    assert estimate["stored_bytes"] == 11 * 1024 * 1024
    assert estimate["runtime_ms"] == 60_000
    assert estimate["compute_usd"] > 0
    assert estimate["storage_for_retention_usd"] > 0
    assert estimate["transactions_usd"] > 0
    assert estimate["estimated_total_usd"] == round(
        estimate["compute_usd"]
        + estimate["storage_for_retention_usd"]
        + estimate["transactions_usd"],
        6,
    )