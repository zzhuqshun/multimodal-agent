"""Fetch the official Qwen ModelScope files and verify published SHA-256 hashes."""
import hashlib
import json
import re
import subprocess
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

root = Path(__file__).resolve().parent
if not (root / "env" / "bin" / "python").is_file():
    raise SystemExit("copy this script to the isolated server model directory after environment setup")
target = root / "models" / "Qwen3.5-9B"
target.mkdir(parents=True, exist_ok=True)
api = "https://modelscope.cn/api/v1/models/Qwen/Qwen3.5-9B"
manifest = root / "state" / "model-source.json"
if manifest.exists():
    selected = json.loads(manifest.read_text())["files"]
else:
    response = subprocess.check_output([
        "curl", "--fail", "--location", "--silent", "--show-error",
        "--connect-timeout", "10", "--max-time", "60", "--retry", "3",
        api + "/repo/files?Revision=master&Recursive=true"])
    files = json.loads(response)["Data"]["Files"]
    selected = [f for f in files if f["Type"] == "blob" and (
        f["Path"].endswith((".json", ".safetensors", ".jinja", ".txt")) or f["Path"] == "LICENSE")]
for item in selected:
    if (Path(item["Path"]).name != item["Path"]
            or not re.fullmatch("[0-9a-f]{64}", item["Sha256"])
            or not re.fullmatch("[0-9a-f]{40}", item["Revision"])):
        raise ValueError("invalid model file path/hash/revision")
if not manifest.exists():
    manifest.write_text(json.dumps({
        "model_id": "Qwen/Qwen3.5-9B", "source": api, "files": selected
    }, indent=2) + "\n")

def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def download(item):
    final = target / item["Path"]
    if final.exists():
        if final.stat().st_size != item["Size"] or checksum(final) != item["Sha256"]:
            raise ValueError("existing model file differs from pinned metadata")
        print("Already verified:", item["Path"], flush=True)
        return
    partial = final.with_name(final.name + ".part")
    url = api + "/repo?" + urllib.parse.urlencode({
        "Revision": item["Revision"], "FilePath": item["Path"]})
    print("Downloading:", item["Path"], item["Size"], flush=True)
    for attempt in range(4):
        transfer = subprocess.run(["curl", "--fail", "--location", "--silent", "--show-error",
                    "--connect-timeout", "15", "--max-time", "1800",
                    "--retry", "3", "--continue-at", "-", "--output", str(partial), url])
        if transfer.returncode == 0:
            break
        if attempt == 3:
            transfer.check_returncode()
        time.sleep(2 ** attempt)
    if partial.stat().st_size != item["Size"] or checksum(partial) != item["Sha256"]:
        raise ValueError("download size/hash mismatch")
    partial.rename(final)
    print("Verified:", item["Path"], flush=True)

with ThreadPoolExecutor(max_workers=2) as executor:
    list(executor.map(download, selected))
(root / "state" / "model-ready").touch()
print("Official model files downloaded and verified.", flush=True)
