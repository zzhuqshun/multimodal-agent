#!/usr/bin/env bash
# Run this copy from the deployed model root; read-only, no generation request.
set -uo pipefail
task_root="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$task_root" || exit 1
printf 'Model root: %s\n' "$task_root"
service_pid=""
if [[ -f state/service.pid ]]; then
    service_pid="$(cat state/service.pid)"
fi
if [[ "$service_pid" =~ ^[1-9][0-9]*$ ]] && [[ -r "/proc/$service_pid/cmdline" ]]; then
    command_line="$(tr '\0' ' ' < "/proc/$service_pid/cmdline")"
    if [[ "$command_line" == *"$task_root/env/bin/vllm"* && "$command_line" == *"$task_root/models/Qwen3.5-9B"* ]]; then
        printf '\nService process:\n'
        ps -p "$service_pid" -o pid,etime,%cpu,%mem,args
    else
        printf '\nService PID does not match this model; PID file may be stale.\n'
    fi
else
    printf '\nService process was not found; check the logs below.\n'
fi
printf '\nGPU status (0%% utilization can mean idle):\n'
nvidia-smi -i "${SMARTFILL_GPU_INDEX:-3}" --query-gpu=index,name,memory.used,memory.free,utilization.gpu --format=csv
printf '\nRegistered model API:\n'
"$task_root/env/bin/python" - <<'PY'
import json
from urllib.request import urlopen
try:
    with urlopen("http://127.0.0.1:18000/v1/models", timeout=5) as response:
        ids = [row["id"] for row in json.load(response)["data"]]
    expected = "smartfill-qwen3.5-9b"
    print("READY" if expected in ids else "EXPECTED MODEL ABSENT", ", ".join(ids))
except Exception as error:
    print("UNREACHABLE:", type(error).__name__)
PY
printf '\nLatest service log:\n'
tail -n 12 logs/vllm-server.log 2>/dev/null || printf 'No service log found.\n'
