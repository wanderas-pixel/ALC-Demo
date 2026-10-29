# Hardened Non-Root Dockerfile for ACME Co. Synthetic Data & Reset Cloud Run Job
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get upgrade -y --no-install-recommends && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --gid 10001 jobgroup && \
    useradd --uid 10001 --gid 10001 --shell /usr/sbin/nologin --no-create-home jobuser

WORKDIR /app
COPY --chown=10001:10001 ../ec_building_brick.ttl /app/ec_building_brick.ttl
COPY --chown=10001:10001 generate_acme_demo_data.py /app/Source_Data/generate_acme_demo_data.py
COPY --chown=10001:10001 parse_brick_ttl.py /app/data_generator/parse_brick_ttl.py
COPY --chown=10001:10001 demo_admin_cli.py /app/data_generator/demo_admin_cli.py

RUN chmod -R 0550 /app

USER 10001:10001

CMD ["python3", "/app/Source_Data/generate_acme_demo_data.py"]


