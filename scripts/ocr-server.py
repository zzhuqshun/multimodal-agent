#!/usr/bin/env python3
"""Small localhost PaddleOCR-VL service; one inference at a time."""
import base64
import binascii
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import logging
from pathlib import Path
import threading
import time

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_REQUEST_BYTES = 28 * 1024 * 1024
MAX_PIXELS = 12_000_000
MAX_PAGES = 10
SERVICE = "smartfill-paddleocr-vl"


def decode_upload(payload):
    if not isinstance(payload, dict) or set(payload) != {"file_type", "file_base64"}:
        raise ValueError("expected file_type and file_base64 only")
    kind = payload["file_type"]
    if kind not in ("png", "jpg", "jpeg", "pdf"):
        raise ValueError("supported file_type: png, jpg, jpeg, pdf")
    encoded = payload["file_base64"]
    if not isinstance(encoded, str):
        raise ValueError("file_base64 must be a string")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("invalid base64") from error
    if not content or len(content) > MAX_FILE_BYTES:
        raise ValueError("file must be nonempty and at most 20 MiB")
    return kind, content


def document_images(kind, content):
    from PIL import Image
    if kind != "pdf":
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in ("PNG", "JPEG"):
                raise ValueError("file contents must be PNG or JPEG")
            if image.width * image.height > MAX_PIXELS:
                raise ValueError("image exceeds 12 million pixels")
            yield image.convert("RGB"), None
        return
    import pypdfium2 as pdfium
    try:
        document = pdfium.PdfDocument(content)
    except pdfium.PdfiumError as error:
        raise ValueError("invalid or unsupported PDF") from error
    with document:
        if not 1 <= len(document) <= MAX_PAGES:
            raise ValueError("PDF must contain 1 to 10 pages")
        # Validate every page before any expensive inference.
        for page in document:
            try:
                width, height = page.get_size()
                if width * height * 4 > MAX_PIXELS:
                    raise ValueError("PDF page exceeds 12 million pixels at 144 DPI")
            finally:
                page.close()
        for page in document:
            try:
                points = list(page.get_size())
                bitmap = page.render(scale=2)
                try:
                    yield bitmap.to_pil().convert("RGB"), points
                finally:
                    bitmap.close()
            finally:
                page.close()


def parse_document(payload, pipeline):
    import numpy as np
    kind, content = decode_upload(payload)
    started = time.perf_counter()
    pages = []
    for index, (image, points) in enumerate(document_images(kind, content), 1):
        # PaddleX ndarray image input uses BGR; positions refer to this image.
        output = list(pipeline.predict(np.asarray(image)[:, :, ::-1].copy(), max_new_tokens=1024))
        if len(output) != 1:
            raise RuntimeError("expected one result per rendered page")
        result = output[0]
        pages.append({
            "page_number": index, "width": image.width, "height": image.height,
            "pdf_size_points": points, "pdf_render_scale": 2 if points else None,
            "result": result.json,
            "markdown": result.markdown.get("markdown_texts", ""),
        })
    return {
        "service": SERVICE, "sha256": sha256(content).hexdigest(),
        "coordinate_system": "pixels, top-left origin, per returned page image",
        "verification_required": True, "max_new_tokens_per_region": 1024,
        "pages": pages, "elapsed_seconds": time.perf_counter() - started,
    }


def load_pipeline(root):
    from paddleocr import PaddleOCRVL
    return PaddleOCRVL(
        pipeline_version="v1.6", device="gpu:0", cpu_threads=4,
        layout_detection_model_dir=str(root / "models/PP-DocLayoutV3"),
        vl_rec_model_dir=str(root / "models/PaddleOCR-VL-1.6"),
        use_layout_detection=True, use_chart_recognition=False,
        use_seal_recognition=False, use_doc_orientation_classify=False,
        use_doc_unwarping=False, use_queues=False,
    )


def main():
    root = Path(__file__).resolve().parent
    import cv2
    cv2.setNumThreads(4)
    pipeline = load_pipeline(root)
    from importlib.metadata import version
    health = {
        "status": "READY", "service": SERVICE,
        "pipeline": "PaddleOCR-VL-1.6", "ocr_models": [
            "PP-DocLayoutV3", "PaddleOCR-VL-1.6-0.9B"],
        "paddleocr": version("paddleocr"), "paddlex": version("paddlex"),
        "paddlepaddle_gpu": version("paddlepaddle-gpu"),
        "features": ["ocr", "layout", "table", "reading_order"],
    }
    # ponytail: one inference at a time; add a worker queue only when throughput requires it.
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(60)

        def respond(self, status, payload):
            data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path != "/health":
                self.respond(404, {"error": "not found"})
                return
            self.respond(200, {**health, "busy": lock.locked()})

        def do_POST(self):
            if self.path != "/parse":
                self.respond(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_REQUEST_BYTES:
                    self.respond(413, {"error": "request exceeds limit or is empty"})
                    return
                if not lock.acquire(blocking=False):
                    self.respond(429, {"error": "OCR busy; retry explicitly later"})
                    return
                try:
                    body = self.rfile.read(length)
                    if len(body) != length:
                        raise ValueError("incomplete body")
                    payload = json.loads(body)
                    result = parse_document(payload, pipeline)
                finally:
                    lock.release()
                self.respond(200, result)
            except (ValueError, OSError) as error:
                self.respond(400, {"error": str(error)})
            except Exception:
                logging.exception("OCR inference failed")
                self.respond(500, {"error": "OCR inference failed; inspect server log"})

    print(json.dumps(health), flush=True)
    ThreadingHTTPServer(("127.0.0.1", 18001), Handler).serve_forever()


if __name__ == "__main__":
    main()
