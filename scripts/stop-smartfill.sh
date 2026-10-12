#!/usr/bin/env bash
# Only signal processes belonging to these exact deployment roots.
set -euo pipefail
task_root="$(cd -- "$(dirname -- "$0")" && pwd)"
"$task_root/qwen3.5-9b/env/bin/python" - "$task_root" <<'PY'
import os
from pathlib import Path
import signal
import sys
root = Path(sys.argv[1])
for name, entry in [('paddleocr-vl', 'ocr-server.py'), ('qwen3.5-9b', 'env/bin/vllm')]:
    directory = root / name
    try:
        pid = int((directory / 'state/service.pid').read_text())
        if pid <= 0:
            raise ValueError('invalid PID')
        fd = os.pidfd_open(pid)
    except (FileNotFoundError, ProcessLookupError, ValueError):
        print(f'Skipped {name}: missing process or invalid PID.')
        continue
    try:
        command = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        if str(directory / entry).encode() not in command:
            print(f'Skipped {name}: PID identity mismatch.')
            continue
        signal.pidfd_send_signal(fd, signal.SIGTERM)
        print(f'Sent SIGTERM to {name} PID {pid}.')
    except (FileNotFoundError, ProcessLookupError):
        print(f'{name} has already exited.')
    finally:
        os.close(fd)
PY
