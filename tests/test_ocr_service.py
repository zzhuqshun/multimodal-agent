"""OCR transport and rendered-source regressions; no model or GPU required."""
import base64
import importlib.util
import io
from pathlib import Path

import pytest
from PIL import Image
import pdfplumber

spec = importlib.util.spec_from_file_location("ocr_server", Path(__file__).parents[1] / "scripts/ocr-server.py")
ocr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ocr)


@pytest.mark.parametrize("payload", [
    {"file_type": "png", "file_base64": "%%%"},
    {"file_type": "png", "file_base64": ""},
    {"file_type": "docx", "file_base64": "eA=="},
    {"file_type": "png", "file_base64": "eA==", "path": "/etc/passwd"},
    {"file_type": "png", "file_base64": 123},
])
def test_untrusted_uploads_are_rejected(payload):
    with pytest.raises(ValueError):
        ocr.decode_upload(payload)


def test_upload_limit_applies_to_decoded_bytes(monkeypatch):
    monkeypatch.setattr(ocr, "MAX_FILE_BYTES", 2)
    with pytest.raises(ValueError, match="20 MiB"):
        ocr.decode_upload({"file_type": "png", "file_base64": base64.b64encode(b"abc").decode()})


def test_pixel_limit_is_checked_before_conversion(monkeypatch):
    data = io.BytesIO()
    Image.new("RGB", (3, 3)).save(data, format="PNG")
    monkeypatch.setattr(ocr, "MAX_PIXELS", 8)
    with pytest.raises(ValueError, match="pixels"):
        list(ocr.document_images("png", data.getvalue()))


def test_file_extension_does_not_bypass_image_validation():
    with pytest.raises(OSError):
        list(ocr.document_images("png", b"arbitrary data"))


def test_pdf_rendering_records_source_scale_and_preserves_page_order(tmp_path):
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    path = tmp_path / "scan.pdf"
    writer = canvas.Canvas(str(path), pagesize=(100, 150))
    for color in ("red", "blue"):
        writer.drawImage(ImageReader(Image.new("RGB", (100, 150), color)), 0, 0, 100, 150)
        writer.showPage()
    writer.save()
    with pdfplumber.open(path) as document:
        assert all(not page.chars for page in document.pages)
    pages = list(ocr.document_images("pdf", path.read_bytes()))
    assert [image.size for image, _ in pages] == [(200, 300), (200, 300)]
    assert [points for _, points in pages] == [[100.0, 150.0]] * 2
    assert pages[0][0].getpixel((100, 100))[0] > 200
    assert pages[1][0].getpixel((100, 100))[2] > 200


def test_overlong_pdf_is_rejected_before_any_page_is_processed(tmp_path, monkeypatch):
    from reportlab.pdfgen import canvas
    path = tmp_path / "long.pdf"
    writer = canvas.Canvas(str(path))
    for _ in range(2):
        writer.showPage()
    writer.save()
    monkeypatch.setattr(ocr, "MAX_PAGES", 1)
    with pytest.raises(ValueError, match="pages"):
        next(ocr.document_images("pdf", path.read_bytes()))


def test_invalid_pdf_is_a_client_input_error():
    with pytest.raises(ValueError, match="PDF"):
        list(ocr.document_images("pdf", b"not a PDF"))
