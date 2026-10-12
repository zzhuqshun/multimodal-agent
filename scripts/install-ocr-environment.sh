#!/usr/bin/env bash
# Deploy in /data/zhuqianshun_data/server/paddleocr-vl beside qwen3.5-9b.
set -euo pipefail
task_root="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$task_root"
mkdir -p runtime cache tmp logs state models config
exec 9>state/service.lock
flock -n 9 || { printf 'OCR service is active; environment was not changed.\n' >&2; exit 1; }
source ./ocr-environment.sh
if [[ ! -x runtime/python/bin/python3.12 ]]; then
    cp -a ../qwen3.5-9b/runtime/python/cpython-3.12.14-linux-x86_64-gnu runtime/python
fi
test -x env/bin/python || uv venv --python "$task_root/runtime/python/bin/python3.12" env
if [[ -f requirements-ocr.lock ]]; then
    uv pip install --python env/bin/python -r requirements-ocr.lock \
        --index https://www.paddlepaddle.org.cn/packages/stable/cu126/ \
        --index-url https://pypi.org/simple --index-strategy unsafe-best-match
else
    uv pip install --python env/bin/python paddlepaddle-gpu==3.2.1 \
        --index-url https://www.paddlepaddle.org.cn/packages/stable/cu126/
    uv pip install --python env/bin/python "paddleocr[doc-parser]==3.7.0" "paddlex[ocr]==3.7.2"
fi
uv pip check --python env/bin/python
uv pip freeze --python env/bin/python >state/requirements-ocr.lock
touch state/vl-environment-ready
