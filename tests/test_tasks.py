"""Tests for asynchronous multi-model document processing."""

import json
from pathlib import Path
from unittest.mock import patch

from app.config import settings
from app.tasks import process_document


def test_runs_and_persists_each_selected_analysis_model(tmp_path: Path) -> None:
    extracted_result = {
        "schema_version": "1.2",
        "document": {"id": "document-1", "filename": "report.pdf"},
        "processing": {"status": "completed", "warnings": []},
        "analysis": {"status": "not_requested"},
        "pages": [{"page_number": 1, "text": "Quarterly report"}],
    }
    first_analysis = {
        "status": "completed",
        "provider": "ollama",
        "model": "qwen2.5:1.5b",
        "summary": "Detailed result",
    }
    second_analysis = {
        "status": "completed",
        "provider": "ollama",
        "model": "qwen2.5:0.5b",
        "summary": "Compact result",
    }

    with (
        patch.object(settings, "data_dir", tmp_path),
        patch.object(settings, "ai_enabled", True),
        patch("app.tasks.process_pdf", return_value=extracted_result),
        patch(
            "app.tasks.analyze_document",
            side_effect=[first_analysis, second_analysis],
        ) as analyze,
        patch.object(process_document, "update_state"),
        patch("app.tasks.database.update_run"),
        patch("app.tasks.database.get_customer_retention", return_value=90),
        patch("app.tasks.database.complete_run") as complete_run,
        patch("app.tasks.database.fail_run"),
    ):
        process_document.run(
            "source.pdf",
            "document-1",
            "report.pdf",
            ["qwen2.5:1.5b", "qwen2.5:0.5b"],
        )
        stored = json.loads(
            (settings.results_dir / "document-1.json").read_text(encoding="utf-8")
        )

    assert [call.kwargs["model"] for call in analyze.call_args_list] == [
        "qwen2.5:1.5b",
        "qwen2.5:0.5b",
    ]
    assert stored["analysis"] == first_analysis
    assert stored["analyses"] == [first_analysis, second_analysis]
    assert stored["document"]["customer"]["id"] == "microsoft"
    assert stored["storage"]["status"] == "not_configured"
    assert stored["cost_estimate"]["estimated_total_usd"] >= 0
    assert complete_run.call_args.args[2]["analyses"] == [
        first_analysis,
        second_analysis,
    ]