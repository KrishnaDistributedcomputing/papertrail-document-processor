"""Extract structured JSON content from native and scanned PDF pages."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any, Callable

import pymupdf
import pytesseract
from PIL import Image

ProgressCallback = Callable[[str, int], None]

_CLASSIFICATION_RULES = {
    "invoice": {
        "invoice": 5,
        "invoice number": 3,
        "bill to": 2,
        "amount due": 2,
        "payment due": 2,
        "subtotal": 1,
    },
    "receipt": {
        "receipt": 5,
        "cashier": 2,
        "change due": 2,
        "thank you for your purchase": 2,
    },
    "contract": {
        "contract": 5,
        "agreement": 3,
        "terms and conditions": 2,
        "hereby": 1,
    },
    "report": {
        "report": 5,
        "executive summary": 3,
        "findings": 2,
        "recommendations": 2,
        "quarterly": 2,
    },
    "resume": {
        "resume": 5,
        "curriculum vitae": 5,
        "work experience": 3,
        "employment history": 2,
    },
    "letter": {
        "dear": 2,
        "sincerely": 2,
        "regards": 1,
    },
    "form": {
        "form": 3,
        "application": 2,
        "please complete": 2,
        "signature": 1,
    },
}


def _classify_document(
    pages: list[dict[str, Any]], metadata: dict[str, Any], filename: str
) -> dict[str, Any]:
    corpus = " ".join(
        [
            filename,
            str(metadata.get("title") or ""),
            str(metadata.get("subject") or ""),
            *(str(page.get("text") or "") for page in pages),
        ]
    ).casefold()
    scores: dict[str, int] = {}
    matches: dict[str, list[str]] = {}

    for category, rules in _CLASSIFICATION_RULES.items():
        matched_terms = [
            term
            for term in rules
            if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", corpus)
        ]
        matches[category] = matched_terms
        scores[category] = sum(rules[term] for term in matched_terms)

    category = max(scores, key=lambda candidate: scores[candidate])
    if scores[category] == 0:
        return {"category": "other", "method": "keyword_rules", "matched_terms": []}
    return {
        "category": category,
        "method": "keyword_rules",
        "matched_terms": matches[category],
    }


def _native_blocks(page: pymupdf.Page) -> tuple[list[dict[str, Any]], str]:
    raw_blocks = page.get_text("dict", sort=True).get("blocks", [])
    spans = [
        span
        for block in raw_blocks
        for line in block.get("lines", [])
        for span in line.get("spans", [])
        if span.get("text", "").strip()
    ]
    body_size = median([float(span.get("size", 0)) for span in spans]) if spans else 0
    blocks: list[dict[str, Any]] = []

    for index, block in enumerate(raw_blocks, start=1):
        lines = block.get("lines", [])
        text = "\n".join(
            "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            for line in lines
        ).strip()
        if not text:
            continue
        sizes = [
            float(span.get("size", 0))
            for line in lines
            for span in line.get("spans", [])
            if span.get("text", "").strip()
        ]
        block_size = max(sizes, default=0)
        block_type = "heading" if body_size and block_size >= body_size * 1.25 else "paragraph"
        blocks.append(
            {
                "id": f"p{page.number + 1}-b{index}",
                "type": block_type,
                "text": text,
                "bbox": [round(value, 2) for value in block.get("bbox", (0, 0, 0, 0))],
                "confidence": 1.0,
                "source": "native",
            }
        )

    return blocks, "\n\n".join(block["text"] for block in blocks)


def _ocr_page(page: pymupdf.Page, dpi: int, languages: str) -> tuple[list[dict[str, Any]], str]:
    pixmap = page.get_pixmap(dpi=dpi, alpha=False)
    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    text = pytesseract.image_to_string(image, lang=languages).strip()
    if not text:
        return [], ""
    return (
        [
            {
                "id": f"p{page.number + 1}-b1",
                "type": "paragraph",
                "text": text,
                "bbox": [0.0, 0.0, round(page.rect.width, 2), round(page.rect.height, 2)],
                "confidence": 0.85,
                "source": "ocr",
            }
        ],
        text,
    )


def process_pdf(
    source_path: Path,
    document_id: str,
    job_id: str,
    original_filename: str,
    *,
    min_native_chars: int = 30,
    ocr_dpi: int = 300,
    ocr_languages: str = "eng",
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Process a PDF and return its versioned JSON representation."""
    started = datetime.now(UTC)
    started_clock = perf_counter()
    source_bytes = source_path.read_bytes()
    pages: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []

    with pymupdf.open(stream=source_bytes, filetype="pdf") as document:
        metadata = document.metadata or {}
        for page_number, page in enumerate(document, start=1):
            if progress:
                progress("extracting", int(((page_number - 1) / max(document.page_count, 1)) * 90))
            blocks, text = _native_blocks(page)
            text_source = "native"
            if len(text.strip()) < min_native_chars:
                if progress:
                    progress("ocr", int(((page_number - 1) / max(document.page_count, 1)) * 90))
                try:
                    blocks, text = _ocr_page(page, ocr_dpi, ocr_languages)
                    text_source = "ocr" if text else "none"
                except pytesseract.TesseractError as error:
                    text_source = "none"
                    warnings.append({"code": "OCR_FAILED", "message": f"Page {page_number}: {error}"})

            pages.append(
                {
                    "page_number": page_number,
                    "width": round(page.rect.width, 2),
                    "height": round(page.rect.height, 2),
                    "rotation": page.rotation,
                    "text_source": text_source,
                    "text": text,
                    "blocks": blocks,
                    "tables": [],
                    "images": [],
                }
            )

        page_count = document.page_count

    completed = datetime.now(UTC)
    status = "completed_with_warnings" if warnings else "completed"
    if progress:
        progress("finalizing", 95)
    return {
        "schema_version": "1.2",
        "document": {
            "id": document_id,
            "filename": original_filename,
            "media_type": "application/pdf",
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
            "size_bytes": len(source_bytes),
            "page_count": page_count,
            "classification": _classify_document(pages, metadata, original_filename),
            "metadata": {
                "title": metadata.get("title") or None,
                "author": metadata.get("author") or None,
                "subject": metadata.get("subject") or None,
            },
        },
        "processing": {
            "job_id": job_id,
            "status": status,
            "started_at": started.isoformat().replace("+00:00", "Z"),
            "completed_at": completed.isoformat().replace("+00:00", "Z"),
            "duration_ms": round((perf_counter() - started_clock) * 1000),
            "ocr_languages": ocr_languages.split("+"),
            "warnings": warnings,
        },
        "analysis": {"status": "not_requested"},
        "pages": pages,
    }