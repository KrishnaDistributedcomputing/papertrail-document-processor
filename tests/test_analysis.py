"""Tests for local AI document analysis."""

import json
from typing import Any
from unittest.mock import patch

from app.analysis import analyze_document


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def test_analyzes_extracted_text_with_structured_ollama_response() -> None:
    result = {
        "document": {
            "filename": "invoice.pdf",
            "classification": {"category": "invoice"},
        },
        "pages": [
            {
                "page_number": 1,
                "text": "Invoice 42 total due is $125.00.",
                "text_source": "native",
                "blocks": [
                    {
                        "text": "Invoice 42 total due is $125.00.",
                        "confidence": 1.0,
                    }
                ],
            }
        ],
    }
    model_response = {
        "total_duration": 1_250_000_000,
        "prompt_eval_count": 42,
        "eval_count": 18,
        "response": json.dumps(
            {
                "summary": "Invoice 42 requests payment of $125.00.",
                "key_points": ["Total due is $125.00"],
                "entities": [{"name": "$125.00", "type": "amount"}],
                "action_items": ["Pay the invoice"],
            }
        )
    }

    with patch("app.analysis.urlopen", return_value=_FakeResponse(model_response)) as request:
        analysis = analyze_document(
            result,
            base_url="http://ollama:11434",
            model="qwen2.5:1.5b",
            timeout_seconds=120,
            max_characters=12000,
        )

    outgoing = json.loads(request.call_args.args[0].data.decode("utf-8"))
    assert request.call_args.args[0].full_url == "http://ollama:11434/api/generate"
    assert outgoing["model"] == "qwen2.5:1.5b"
    assert outgoing["stream"] is False
    assert outgoing["format"]["type"] == "object"
    assert "Invoice 42 total due is $125.00." in outgoing["prompt"]
    expected_characters = len("[Page 1]\nInvoice 42 total due is $125.00.")
    assert analysis == {
        "status": "completed",
        "provider": "ollama",
        "model": "qwen2.5:1.5b",
        "confidence": {
            "score": 100,
            "level": "high",
            "method": "input_quality_v1",
            "extraction_quality": 100,
            "context_coverage": 100,
            "characters_analyzed": expected_characters,
            "characters_available": expected_characters,
        },
        "performance": {
            "duration_ms": 1250,
            "prompt_tokens": 42,
            "output_tokens": 18,
        },
        "summary": "Invoice 42 requests payment of $125.00.",
        "key_points": ["Total due is $125.00"],
        "entities": [{"name": "$125.00", "type": "amount"}],
        "action_items": ["Pay the invoice"],
    }


def test_reduces_confidence_when_ocr_text_is_truncated() -> None:
    result = {
        "document": {
            "filename": "scan.pdf",
            "classification": {"category": "other"},
        },
        "pages": [
            {
                "page_number": 1,
                "text": "A" * 100,
                "text_source": "ocr",
                "blocks": [{"text": "A" * 100, "confidence": 0.85}],
            }
        ],
    }
    model_response = {
        "response": json.dumps(
            {"summary": "Scan", "key_points": [], "entities": [], "action_items": []}
        )
    }

    with patch("app.analysis.urlopen", return_value=_FakeResponse(model_response)):
        analysis = analyze_document(
            result,
            base_url="http://ollama:11434",
            model="qwen2.5:1.5b",
            timeout_seconds=120,
            max_characters=20,
        )

    confidence = analysis["confidence"]
    assert confidence["score"] == 65
    assert confidence["level"] == "medium"
    assert confidence["extraction_quality"] == 85
    assert confidence["context_coverage"] == 18
    assert confidence["characters_analyzed"] == 20
    assert confidence["characters_available"] == 109