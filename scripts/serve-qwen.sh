#!/usr/bin/env bash
# Run in the foreground; all model-specific files stay beside this script.
set -euo pipefail
task_root="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$task_root"
test -f state/environment-ready && test -f state/model-ready
exec 9>state/service.lock
flock -n 9 || { printf 'This model service is already locked.\n' >&2; exit 1; }
export UV_CACHE_DIR="$task_root/cache/uv"
export UV_PYTHON_INSTALL_DIR="$task_root/runtime/python"
export XDG_CACHE_HOME="$task_root/cache"
export XDG_CONFIG_HOME="$task_root/config"
export XDG_DATA_HOME="$task_root/runtime/data"
export XDG_STATE_HOME="$task_root/state"
export VLLM_CONFIG_ROOT="$task_root/config/vllm"
export HF_HUB_DISABLE_TELEMETRY=1
export TMPDIR="$task_root/tmp"
export HF_HOME="$task_root/cache/huggingface"
export HF_HUB_OFFLINE=1
export MODELSCOPE_CACHE="$task_root/cache/modelscope"
export VLLM_CACHE_ROOT="$task_root/cache/vllm"
export TORCHINDUCTOR_CACHE_DIR="$task_root/cache/torchinductor"
export TRITON_CACHE_DIR="$task_root/cache/triton"
export CUDA_CACHE_PATH="$task_root/cache/cuda"
export NUMBA_CACHE_DIR="$task_root/cache/numba"
export OMP_NUM_THREADS=4
export MKL_NUM_THREADS=4
export MAX_JOBS=2
export RAYON_NUM_THREADS=4
export TOKENIZERS_PARALLELISM=false
export VLLM_NO_USAGE_STATS=1
export DO_NOT_TRACK=1
gpu_index="${SMARTFILL_GPU_INDEX:-3}"
# ponytail: this is a shared-server availability check, not a GPU scheduler.
nvidia-smi -i "$gpu_index" --query-gpu=memory.free,utilization.gpu --format=csv,noheader,nounits |
    "$task_root/env/bin/python" -c 'import sys; free,usage=map(int,sys.stdin.read().split(",")); assert free>=45000 and usage==0, "selected GPU is busy; service was not started"'
gpu_uuid="$(nvidia-smi -i "$gpu_index" --query-gpu=uuid --format=csv,noheader)"
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export CUDA_VISIBLE_DEVICES="$gpu_index"
"$task_root/env/bin/python" -c 'import socket,sys,torch; assert str(torch.cuda.get_device_properties(0).uuid)==sys.argv[1].removeprefix("GPU-"), "CUDA/NVML device mapping mismatch"; s=socket.socket(); s.bind(("127.0.0.1",18000)); s.close()' "$gpu_uuid"
printf '%s\n' "$$" > state/service.pid
exec nice -n 10 "$task_root/env/bin/vllm" serve "$task_root/models/Qwen3.5-9B" \
    --served-model-name smartfill-qwen3.5-9b \
    --host 127.0.0.1 --port 18000 \
    --tensor-parallel-size 1 --dtype bfloat16 \
    --max-model-len 8192 --max-num-seqs 1 \
    --gpu-memory-utilization 0.32 --enforce-eager \
    --reasoning-parser qwen3 \
    --limit-mm-per-prompt '{"image":1,"video":0}'
