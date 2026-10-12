#!/usr/bin/env python3
"""Download official Paddle model archives and record local integrity hashes."""
import hashlib
import fcntl
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent
MODELS = ["PP-DocLayoutV3", "PaddleOCR-VL-1.6"]
BASE = "https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    records = []
    for name in MODELS:
        url = BASE + "/" + name + "_infer.tar"
        archive = ROOT / "cache" / (name + "_infer.tar")
        destination = ROOT / "models" / name
        if not destination.exists():
            args = ["curl", "--fail", "--location", "--connect-timeout", "15",
                    "--max-time", "1800", "--retry", "2", "--continue-at", "-",
                    "--output", str(archive)]
            ip = os.environ.get("SMARTFILL_DOWNLOAD_IP")
            if ip:
                args += ["--resolve", "paddle-model-ecology.bj.bcebos.com:443:" + ip]
            subprocess.run(args + [url], check=True)
            with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temporary:
                staging = Path(temporary)
                with tarfile.open(archive) as bundle:
                    bundle.extractall(staging, filter="data")
                directories = [p for p in staging.iterdir() if p.is_dir()]
                if len(directories) != 1:
                    raise ValueError("expected one model directory in archive")
                directories[0].rename(destination)
        records.append({
            "name": name, "url": url,
            "archive_sha256": digest(archive) if archive.exists() else None,
            "archive_bytes": archive.stat().st_size if archive.exists() else None,
            "files": [{"path": str(p.relative_to(destination)), "bytes": p.stat().st_size,
                       "sha256": digest(p)}
                      for p in sorted(destination.rglob("*")) if p.is_file()],
        })
        (ROOT / "state/model-source.json").write_text(
            json.dumps({"hash_scope": "local integrity record; no publisher SHA supplied",
                        "models": records}, indent=2) + "\n")
    (ROOT / "state/model-ready").touch()


if __name__ == "__main__":
    with (ROOT / "state/service.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("OCR service is active; model files were not changed.")
        main()
