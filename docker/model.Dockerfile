# Сервис локальной модели (GPU): Qwen3-4B-Instruct-2507, NF4, JSON-схема на выходе.
# Сборка:  docker compose -f compose.yaml -f compose.llm.yaml build model
# Версии закреплены так же, как в окружении, на котором проводились измерения (docs/39).
ARG PYTHON_IMAGE=python:3.12-slim@sha256:6c4dd321d176d61ea848dc8c73a4f7dbae8f70e0ee48bb411ea2f045b599fa8e
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PIP_NO_CACHE_DIR=1
RUN pip install torch==2.7.1 --index-url https://download.pytorch.org/whl/cu128 \
 && pip install transformers==4.57.1 accelerate==1.10.1 peft==0.17.1 safetensors==0.6.2 \
      lm-format-enforcer==0.11.3 bitsandbytes==0.50.0 \
      fastapi==0.142.2 uvicorn==0.54.0 pydantic==2.13.5 httpx==0.28.1 PyYAML==6.0.3 sqlalchemy==2.0.54 numpy==2.5.3
WORKDIR /app
COPY src src
COPY ml/local_model.py ml/local_model.py
RUN useradd --uid 10001 --no-create-home model && mkdir -p /diagnostics /gpu-cache && chown 10001 /diagnostics /gpu-cache
USER 10001:10001
ENV FSP_LOCAL_MODEL_PATH=/model FSP_LOCAL_MODEL_MANIFEST=/model-manifest.json \
    FSP_LOCAL_MODEL_STARTUP_REPORT=/diagnostics/startup.json \
    TRITON_CACHE_DIR=/gpu-cache/triton CUDA_CACHE_PATH=/gpu-cache/cuda HOME=/tmp
EXPOSE 8001
HEALTHCHECK --interval=15s --timeout=5s --start-period=240s --retries=10 \
  CMD python -c "import urllib.request,json,sys; sys.exit(0 if json.load(urllib.request.urlopen('http://127.0.0.1:8001/health',timeout=3)).get('status')=='ready' else 1)"
CMD ["python", "-m", "ml.local_model"]
