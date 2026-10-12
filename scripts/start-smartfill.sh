#!/usr/bin/env bash
# Deploy beside qwen3.5-9b/ and paddleocr-vl/.
set -euo pipefail
task_root="$(cd -- "$(dirname -- "$0")" && pwd)"
exec 8>"$task_root/.smartfill-start.lock"
flock -n 8 || { printf 'Another combined startup is in progress.\n' >&2; exit 1; }
python="$task_root/qwen3.5-9b/env/bin/python"

check_api() {
    "$python" - "$1" "$2" <<'PY'
import json, sys
from urllib.request import urlopen
try:
    with urlopen(sys.argv[1], timeout=3) as response:
        data = json.load(response)
    expected = sys.argv[2]
    ok = (any(row.get("id") == expected for row in data.get("data", []))
          if expected == "smartfill-qwen3.5-9b"
          else data.get("service") == expected and data.get("status") == "READY")
    sys.exit(0 if ok else 1)
except Exception:
    sys.exit(1)
PY
}

start_one() {
    local directory="$1" script="$2" log="$3" url="$4" expected="$5" marker="$6"
    if check_api "$url" "$expected"; then
        printf '%s is already READY; reusing it.\n' "$expected"
        return
    fi
    if [[ -f "$directory/state/service.pid" ]]; then
        local pid
        pid="$(cat "$directory/state/service.pid")"
        if [[ "$pid" =~ ^[1-9][0-9]*$ ]] && [[ -r "/proc/$pid/cmdline" ]] &&
            tr '\0' ' ' <"/proc/$pid/cmdline" | grep -Fq "$directory/$marker"; then
            printf '%s is loading; waiting for readiness.\n' "$expected"
            return
        fi
    fi
    (cd "$directory"; nohup bash "./$script" >>"$log" 2>&1 </dev/null 8>&- &)
    printf 'Starting %s; log: %s/%s\n' "$expected" "$directory" "$log"
}

start_one "$task_root/qwen3.5-9b" serve-qwen.sh logs/vllm-server.log \
    http://127.0.0.1:18000/v1/models smartfill-qwen3.5-9b env/bin/vllm
start_one "$task_root/paddleocr-vl" serve-ocr.sh logs/ocr-server.log \
    http://127.0.0.1:18001/health smartfill-paddleocr-vl ocr-server.py
for ((attempt=0; attempt<120; attempt++)); do
    if check_api http://127.0.0.1:18000/v1/models smartfill-qwen3.5-9b &&
       check_api http://127.0.0.1:18001/health smartfill-paddleocr-vl; then
        printf 'READY: Qwen :18000 and PaddleOCR-VL-1.6 :18001\n'
        exit 0
    fi
    sleep 5
done
printf 'Startup timed out; inspect both service logs. Running services were retained.\n' >&2
exit 1
