# Hardened Non-Root Dockerfile for ACME Co. Agent Gateway (acme-abo-agent-gateway)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080 \
    USE_GCP_OTEL_EXPORTER=true \
    EMIT_STRUCTURED_OTEL_LOGS=true

RUN apt-get update && \
    apt-get upgrade -y --no-install-recommends && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --gid 10001 appgroup && \
    useradd --uid 10001 --gid 10001 --shell /usr/sbin/nologin --no-create-home appuser

WORKDIR /app

COPY requirements.txt ./agents/requirements.txt
RUN pip install --no-cache-dir -r ./agents/requirements.txt fastapi "uvicorn[standard]" google-auth

COPY --chown=10001:10001 . ./agents/

RUN chown -R 10001:10001 /app && chmod -R 0555 /app

USER 10001:10001
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/healthz', timeout=3)"]

CMD ["uvicorn", "agents.gateway.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-server-header", "--proxy-headers"]

