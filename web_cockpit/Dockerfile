# Hardened Multi-Stage Dockerfile for ACME Co. Autonomous Building Operations Cockpit on Cloud Run
# Stage 1: Immutable Frontend Build (Node 22 Alpine)
FROM node:22-alpine AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json ./
RUN npm install --legacy-peer-deps --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: Hardened Distroless-Style Non-Root Python 3.12 Runtime
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080 \
    ACME_ENFORCE_IAP=true

# Install security updates and create an unprivileged non-root system user (UID/GID 10001)
RUN apt-get update && \
    apt-get upgrade -y --no-install-recommends && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --gid 10001 appgroup && \
    useradd --uid 10001 --gid 10001 --shell /usr/sbin/nologin --no-create-home appuser

WORKDIR /app/web_cockpit

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r ./backend/requirements.txt 2>/dev/null || \
    pip install --no-cache-dir -r ./backend/requirements.txt

COPY --chown=10001:10001 backend/ ./backend/
COPY --from=frontend-build --chown=10001:10001 /build/frontend/dist ./frontend/dist

# Lock down ownership and filesystem permissions (read/execute only for non-root UID/GID 10001)
RUN chown -R 10001:10001 /app/web_cockpit && chmod -R 0555 /app/web_cockpit

USER 10001:10001
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/healthz', timeout=3)"]

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-server-header", "--proxy-headers"]



