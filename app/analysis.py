"""Generate grounded document insights with a local Ollama model."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from jsonschema import ValidationError, validate


class AnalysisError(RuntimeError):
    """Raised when the local AI service cannot produce valid analysis."""


_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "minLength": 1},
        "key_points": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                },
                "required": ["name", "type"],
            },
            "maxItems": 10,
        },
        "action_items": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
    },
    "required": ["summary", "key_points", "entities", "action_items"],
}

_JSON_FORMAT_MODEL_PREFIXES = ("llama3.2:",)


def _document_context(result: dict[str, Any], max_characters: int) -> tuple[str, int]:
    sections = [
        f"[Page {page.get('page_number', index)}]\n{str(page.get('text') or '').strip()}"
        for index, page in enumerate(result.get("pages", []), start=1)
        if str(page.get("text") or "").strip()
    ]
    available_text = "\n\n".join(sections)
    return available_text[:max(0, max_characters)], len(available_text)


def _evidence_confidence(
    result: dict[str, Any],
    *,
    characters_analyzed: int,
    characters_available: int,
) -> dict[str, Any]:
    weighted_quality = 0.0
    weighted_characters = 0
    source_quality = {"native": 1.0, "ocr": 0.85, "none": 0.0}

    for page in result.get("pages", []):
        page_has_blocks = False
        for block in page.get("blocks", []):
            block_text = str(block.get("text") or "").strip()
            if not block_text:
                continue
            page_has_blocks = True
            character_count = len(block_text)
            try:
                quality = float(block.get("confidence", 0.0))
            except (TypeError, ValueError):
                quality = 0.0
            weighted_quality += max(0.0, min(quality, 1.0)) * character_count
            weighted_characters += character_count

        page_text = str(page.get("text") or "").strip()
        if page_text and not page_has_blocks:
            character_count = len(page_text)
            quality = source_quality.get(str(page.get("text_source") or ""), 0.5)
            weighted_quality += quality * character_count
            weighted_characters += character_count

    extraction_quality = weighted_quality / weighted_characters if weighted_characters else 0.0
    context_coverage = (
        min(characters_analyzed / characters_available, 1.0)
        if characters_available
        else 0.0
    )
    score = round((extraction_quality * 0.7 + context_coverage * 0.3) * 100)
    level = "high" if score >= 85 else "medium" if score >= 65 else "low"
    return {
        "score": score,
        "level": level,
        "method": "input_quality_v1",
        "extraction_quality": round(extraction_quality * 100),
        "context_coverage": round(context_coverage * 100),
        "characters_analyzed": characters_analyzed,
        "characters_available": characters_available,
    }


def _string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    strings: list[str] = []
    for item in value:
        if isinstance(item, dict):
            text = str(
                item.get("text")
                or item.get("task")
                or item.get("action")
                or item.get("description")
                or ""
            ).strip()
            details = []
            for label in ("owner", "deadline"):
                detail = str(item.get(label) or "").strip()
                if detail and detail.casefold() not in text.casefold():
                    details.append(f"{label}: {detail}")
            if text and details:
                text = f"{text} ({'; '.join(details)})"
        else:
            text = str(item).strip()
        if text:
            strings.append(text)
    return strings[:limit]


def _entities(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    entities: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        entity_type = str(item.get("type") or "").strip()
        if name and entity_type:
            entities.append({"name": name, "type": entity_type})
    return entities[:10]


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _normalize_analysis(generated: dict[str, Any]) -> dict[str, Any]:
    key_points = _string_list(generated.get("key_points"), 5)
    summary = str(generated.get("summary") or "").strip()
    if not summary and key_points:
        summary = key_points[0]
    normalized = {
        "summary": summary,
        "key_points": key_points,
        "entities": _entities(generated.get("entities")),
        "action_items": _string_list(generated.get("action_items"), 5),
    }
    try:
        validate(instance=normalized, schema=_ANALYSIS_SCHEMA)
    except ValidationError as error:
        raise AnalysisError(
            f"Local AI analysis returned invalid structured JSON: {error.message}"
        ) from error
    return normalized


def _generate_analysis(
    *,
    base_url: str,
    payload: dict[str, Any],
    timeout_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    request = Request(
        f"{base_url.rstrip('/')}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            ollama_payload = json.loads(response.read().decode("utf-8"))
        generated = json.loads(str(ollama_payload.get("response") or ""))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as error:
        raise AnalysisError(f"Local AI analysis failed: {error}") from error

    if not isinstance(generated, dict):
        raise AnalysisError("Local AI analysis returned an invalid JSON object.")
    return ollama_payload, generated


def analyze_document(
    result: dict[str, Any],
    *,
    base_url: str,
    model: str,
    timeout_seconds: int,
    max_characters: int,
) -> dict[str, Any]:
    """Analyze extracted document text using a local Ollama endpoint."""
    text, characters_available = _document_context(result, max_characters)
    if not text:
        return {
            "status": "skipped",
            "provider": "ollama",
            "model": model,
            "reason": "No extracted text was available for analysis.",
        }

    document = result.get("document", {})
    category = document.get("classification", {}).get("category", "other")
    use_json_format = model.startswith(_JSON_FORMAT_MODEL_PREFIXES)
    if use_json_format:
        prompt = (
            "Analyze only the supplied document text. Return one JSON object with exactly these "
            "fields: summary (a concise factual string), key_points (an array of up to 5 explicit "
            "facts), entities (an array of objects with name and type strings for named people, "
            "organizations, dates, amounts, and locations), and action_items (an array of up to "
            "5 strings describing explicit tasks, recommendations, owners, or deadlines). Do not "
            "invent facts. Use "
            "an empty array only when no matching evidence exists.\n\n"
            f"Filename: {document.get('filename', 'document.pdf')}\n"
            f"Category: {category}\n\n"
            f"DOCUMENT TEXT\n{text}"
        )
    else:
        prompt = (
            "Analyze the document below using only its supplied text. Do not infer missing facts. "
            "Write a concise factual summary, up to five key points, named entities with simple "
            "types such as person, organization, date, amount, or location, and explicit action "
            "items. Return exactly these fields: summary, key_points, entities, and action_items. "
            "Use empty arrays only when the document contains no matching evidence.\n\n"
            f"Filename: {document.get('filename', 'document.pdf')}\n"
            f"Existing rule-based category: {category}\n\n"
            f"DOCUMENT TEXT\n{text}"
        )
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json" if use_json_format else _ANALYSIS_SCHEMA,
        "options": {"temperature": 0 if use_json_format else 0.1},
        "keep_alive": "10m",
    }
    ollama_payload, generated = _generate_analysis(
        base_url=base_url,
        payload=payload,
        timeout_seconds=timeout_seconds,
    )
    normalized = _normalize_analysis(generated)

    return {
        "status": "completed",
        "provider": "ollama",
        "model": model,
        "confidence": _evidence_confidence(
            result,
            characters_analyzed=len(text),
            characters_available=characters_available,
        ),
        "performance": {
            "duration_ms": round(_nonnegative_int(ollama_payload.get("total_duration")) / 1_000_000),
            "prompt_tokens": _nonnegative_int(ollama_payload.get("prompt_eval_count")),
            "output_tokens": _nonnegative_int(ollama_payload.get("eval_count")),
        },
        **normalized,
    }