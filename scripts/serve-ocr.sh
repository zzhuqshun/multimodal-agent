#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$task_root"
test -f state/vl-environment-ready && test -f state/model-ready
exec 9>state/service.lock
flock -n 9 || { printf 'OCR service already locked.\n' >&2; exit 1; }
source ./ocr-environment.sh
gpu_index="${SMARTFILL_GPU_INDEX:-3}"
nvidia-smi -i "$gpu_index" --query-gpu=memory.free --format=csv,noheader,nounits |
    env/bin/python -c 'import sys; assert int(sys.stdin.read())>=12000, "selected GPU has insufficient free memory"'
export CUDA_VISIBLE_DEVICES="$(nvidia-smi -i "$gpu_index" --query-gpu=uuid --format=csv,noheader)"
env/bin/python -c 'import socket; s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); s.bind(("127.0.0.1",18001)); s.close()'
printf '%s\n' "$$" >state/service.pid
exec nice -n 10 "$task_root/env/bin/python" "$task_root/ocr-server.py"
