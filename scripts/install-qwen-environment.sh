#!/usr/bin/env bash
# Copy this script and docs/requirements-server.lock to the server model root.
set -euo pipefail
task_root="$(cd -- "$(dirname -- "$0")" && pwd)"
test -f "$task_root/requirements-server.lock" || { printf 'Missing server requirements lock.\n' >&2; exit 1; }
mkdir -p "$task_root"/{runtime,cache,tmp,logs,state,models}
exec 9>"$task_root/state/service.lock"
flock -n 9 || { printf 'Stop this model service before changing its environment.\n' >&2; exit 1; }
export UV_CACHE_DIR="$task_root/cache/uv"
export UV_PYTHON_INSTALL_DIR="$task_root/runtime/python"
export UV_PYTHON_BIN_DIR="$task_root/runtime/bin"
export XDG_CACHE_HOME="$task_root/cache"
export XDG_CONFIG_HOME="$task_root/config"
export XDG_DATA_HOME="$task_root/runtime/data"
export XDG_STATE_HOME="$task_root/state"
export TMPDIR="$task_root/tmp"
export UV_CONCURRENT_DOWNLOADS=2
export UV_CONCURRENT_INSTALLS=2
export UV_CONCURRENT_BUILDS=1
if [ ! -x "$task_root/env/bin/python" ]; then
    uv --no-config venv --python 3.12.14 "$task_root/env"
fi
uv --no-config pip install --python "$task_root/env/bin/python" --torch-backend=cu128 -r "$task_root/requirements-server.lock"
uv --no-config pip freeze --python "$task_root/env/bin/python" > "$task_root/state/requirements-server.lock"
touch "$task_root/state/environment-ready"
