"""Tests for PDF content processing."""

import hashlib
from io import BytesIO
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont

from app.processor import process_pdf


def test_processes_native_pdf_without_ocr(tmp_path: Path) -> None:
    source_path = tmp_path / "sample.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Quarterly Operations Report", fontsize=20)
    page.insert_text((72, 112), "Revenue increased by twelve percent this quarter.", fontsize=11)
    document.set_metadata({"title": "Operations Report", "author": "Papertrail"})
    document.save(source_path)
    document.close()

    result = process_pdf(
        source_path,
        "document-1",
        "job-1",
        "sample.pdf",
        min_native_chars=10,
    )

    assert result["schema_version"] == "1.2"
    assert result["document"]["page_count"] == 1
    assert result["document"]["sha256"] == hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert result["document"]["metadata"]["title"] == "Operations Report"
    assert result["document"]["classification"]["category"] == "report"
    assert result["document"]["classification"]["method"] == "keyword_rules"
    assert "report" in result["document"]["classification"]["matched_terms"]
    assert result["pages"][0]["text_source"] == "native"
    assert "Revenue increased" in result["pages"][0]["text"]
    assert result["pages"][0]["blocks"][0]["bbox"]
    assert result["processing"]["warnings"] == []
    assert result["analysis"] == {"status": "not_requested"}


def test_processes_scanned_pdf_with_downloaded_ocr_model(tmp_path: Path) -> None:
    source_path = tmp_path / "scanned.pdf"
    image = Image.new("RGB", (1600, 500), "white")
    font_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    font = ImageFont.truetype(str(font_path), 72) if font_path.exists() else ImageFont.load_default()
    ImageDraw.Draw(image).text((100, 180), "SCANNED INVOICE 2026", fill="black", font=font)
    image_bytes = BytesIO()
    image.save(image_bytes, format="PNG")

    document = pymupdf.open()
    page = document.new_page(width=800, height=250)
    page.insert_image(page.rect, stream=image_bytes.getvalue())
    document.save(source_path)
    document.close()

    result = process_pdf(source_path, "document-2", "job-2", "scanned.pdf")

    assert result["pages"][0]["text_source"] == "ocr"
    assert "SCANNED INVOICE 2026" in result["pages"][0]["text"]
    assert result["pages"][0]["blocks"][0]["source"] == "ocr"
    assert result["document"]["classification"]["category"] == "invoice"


def test_classifies_document_without_signals_as_other(tmp_path: Path) -> None:
    source_path = tmp_path / "unclassified.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Platform performance overview and system metrics.", fontsize=11)
    document.save(source_path)
    document.close()

    result = process_pdf(
        source_path,
        "document-3",
        "job-3",
        "unclassified.pdf",
        min_native_chars=10,
    )

    assert result["document"]["classification"] == {
        "category": "other",
        "method": "keyword_rules",
        "matched_terms": [],
    }