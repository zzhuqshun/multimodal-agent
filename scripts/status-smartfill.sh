#!/usr/bin/env bash
set -uo pipefail
task_root="$(cd -- "$(dirname -- "$0")" && pwd)"
bash "$task_root/qwen3.5-9b/status-qwen.sh"
printf '\nPaddleOCR-VL-1.6 process and API:\n'
ocr_root="$task_root/paddleocr-vl"
if [[ -f "$ocr_root/state/service.pid" ]]; then
    pid="$(cat "$ocr_root/state/service.pid")"
    if [[ "$pid" =~ ^[1-9][0-9]*$ ]] && [[ -r "/proc/$pid/cmdline" ]] &&
        tr '\0' ' ' <"/proc/$pid/cmdline" | grep -Fq "$ocr_root/ocr-server.py"; then
        ps -p "$pid" -o pid,etime,%cpu,%mem,args
    else
        printf 'OCR process absent or PID identity mismatch.\n'
    fi
fi
"$task_root/qwen3.5-9b/env/bin/python" - <<'PY'
import json
from urllib.request import urlopen
try:
    with urlopen("http://127.0.0.1:18001/health",timeout=5) as response:
        print(json.dumps(json.load(response),ensure_ascii=False,indent=2))
except Exception as error:
    print("OCR UNREACHABLE:",type(error).__name__)
PY
printf '\nLatest OCR log:\n'
tail -n 12 "$ocr_root/logs/ocr-server.log"
