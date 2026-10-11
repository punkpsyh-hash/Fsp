#!/bin/bash
# Запуск python в D-backed контейнере: dr.sh [--gpu] script args...  (сеть выключена, корень проекта read-only)
P="$(cd "$(dirname "$0")/.." && pwd -W 2>/dev/null || pwd)"
GPU=""; if [ "$1" = "--gpu" ]; then GPU="--gpus all"; shift; fi
MSYS_NO_PATHCONV=1 docker run --rm --pull never $GPU --network none --cpus 8 --memory 12g --shm-size 1g \
 --mount "type=bind,source=$P,target=/workspace/Fsp,readonly" \
 --mount "type=bind,source=$P/ml/datasets,target=/workspace/Fsp/ml/datasets" \
 --mount "type=bind,source=$P/ml/runs,target=/workspace/Fsp/ml/runs" \
 --mount "type=bind,source=$P/ml/adapters,target=/workspace/Fsp/ml/adapters" \
 --mount "type=bind,source=D:/Codex/Caches/fsp-llm,target=/cache" \
 -w /workspace/Fsp -e PYTHONPATH=/cache/site-packages:/workspace/Fsp -e PYTHONDONTWRITEBYTECODE=1 \
 -e TMPDIR=/cache/tmp -e HF_HOME=/cache/hf -e HF_HUB_OFFLINE=1 -e PYTHONIOENCODING=utf8 \
 -e TRITON_CACHE_DIR=/cache/triton -e CUDA_CACHE_PATH=/cache/cuda \
 --entrypoint /cache/pilot-venv/bin/python hermes-dashboard-fastapi:latest "$@"
