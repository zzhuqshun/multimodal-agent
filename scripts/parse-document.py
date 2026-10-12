#!/usr/bin/env python3
"""Call the isolated OCR service through an SSH localhost forward."""
import argparse
import base64
import json
import math
from hashlib import sha256
from pathlib import Path
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser()
parser.add_argument("document", type=Path)
parser.add_argument("--output", required=True, type=Path)
parser.add_argument("--url", default="http://127.0.0.1:18001")
parser.add_argument("--timeout", type=float, default=180)
args = parser.parse_args()
if args.output.exists():
    parser.error("output already exists")
if not math.isfinite(args.timeout) or args.timeout <= 0:
    parser.error("timeout must be positive")
kind = args.document.suffix.lstrip(".").lower()
if kind not in ("png", "jpg", "jpeg", "pdf"):
    parser.error("supported inputs: PNG, JPEG, PDF")
if not 0 < args.document.stat().st_size <= 20 * 1024 * 1024:
    parser.error("document must be nonempty and at most 20 MiB")
content = args.document.read_bytes()
payload = {"file_type": kind,
           "file_base64": base64.b64encode(content).decode()}
request = Request(args.url.rstrip("/") + "/parse",
                  data=json.dumps(payload).encode(),
                  headers={"Content-Type": "application/json"})
with urlopen(request, timeout=args.timeout) as response:
    data = response.read(64 * 1024 * 1024 + 1)
if len(data) > 64 * 1024 * 1024:
    raise ValueError("OCR response exceeds 64 MiB")
result = json.loads(data)
if result.get("service") != "smartfill-paddleocr-vl" or not result.get("pages"):
    raise ValueError("unexpected OCR response")
if result.get("sha256") != sha256(content).hexdigest():
    raise ValueError("OCR result does not identify the uploaded source bytes")
args.output.parent.mkdir(parents=True, exist_ok=True)
with args.output.open("x", encoding="utf-8") as stream:
    json.dump(result, stream, ensure_ascii=False, indent=2)
    stream.write("\n")
print(json.dumps({"pages": len(result["pages"]), "sha256": result["sha256"],
                  "elapsed_seconds": result["elapsed_seconds"],
                  "output": str(args.output)}, ensure_ascii=False))
