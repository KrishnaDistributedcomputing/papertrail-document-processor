"""Tests for token usage and local model compute estimates."""

from pathlib import Path
from unittest.mock import patch

from app import database
from app.config import settings
from app.main import get_token_usage_overview


def test_aggregates_token_usage_by_model_and_customer(tmp_path: Path) -> None:
    result = {
        "document": {"size_bytes": 1024},
        "processing": {"status": "completed", "warnings": []},
        "analysis": {},
        "analyses": [
            {
                "status": "completed",
                "model": "qwen2.5:1.5b",
                "performance": {
                    "prompt_tokens": 800,
                    "output_tokens": 200,
                    "duration_ms": 30_000,
                },
            },
            {
                "status": "completed",
                "model": "qwen2.5:0.5b",
                "performance": {
                    "prompt_tokens": 700,
                    "output_tokens": 100,
                    "duration_ms": 15_000,
                },
            },
        ],
        "pages": [],
        "storage": {"status": "planned"},
        "cost_estimate": {},
    }

    with patch.object(settings, "data_dir", tmp_path):
        database.create_run(
            job_id="token-job",
            document_id="token-document",
            batch_id=None,
            customer_id="microsoft",
            filename="tokens.pdf",
            source_path=tmp_path / "tokens.pdf",
        )
        database.complete_run("token-job", tmp_path / "tokens.json", result)
        payload = get_token_usage_overview()
        filtered = get_token_usage_overview("microsoft")

    assert payload["provider"] == "Ollama"
    assert payload["billing_model"] == "local_runtime"
    assert payload["totals"]["completed_documents"] == 1
    assert payload["totals"]["model_calls"] == 2
    assert payload["totals"]["prompt_tokens"] == 1500
    assert payload["totals"]["output_tokens"] == 300
    assert payload["totals"]["total_tokens"] == 1800
    assert payload["totals"]["metered_token_cost_usd"] == 0
    assert payload["totals"]["illustrative_azure_ai_cost_usd"] == 0.000405
    assert payload["totals"]["estimated_compute_cost_usd"] == 0.0015
    assert payload["pricing"]["azure_sample_input_1m_tokens_usd"] == 0.15
    assert payload["pricing"]["azure_sample_output_1m_tokens_usd"] == 0.60
    assert payload["pricing"]["effective_compute_hour_usd"] == 0.12
    assert [model["id"] for model in payload["models"]] == [
        "qwen2.5:1.5b",
        "qwen2.5:0.5b",
    ]
    assert payload["customers"][0]["name"] == "Microsoft"
    assert payload["customers"][0]["total_tokens"] == 1800
    assert payload["customers"][0]["illustrative_azure_ai_cost_usd"] == 0.000405
    assert len(payload["recent_calls"]) == 2
    assert filtered["scope"] == "customer"
    assert filtered["customer_id"] == "microsoft"
    assert filtered["totals"] == payload["totals"]