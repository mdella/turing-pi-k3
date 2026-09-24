# Hombre (lovethatbrandx/hombre) web UI for Honcho — local build.
# Differs from upstream's Dockerfile: no Docker CLI/compose (its container-control features need the Docker
# socket and are meaningless on k3s; upstream also fetches x86_64-only binaries), runs as non-root,
# and state goes to /data. Build context = a checkout of the upstream repo at the pinned commit.
FROM python:3.12-slim
RUN adduser --system --group --home /app hombre
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=hombre:hombre . .
ENV HOMBRE_DATA_DIR=/data HOMBRE_LOG_DIR=/data/logs HOMBRE_ENV_PATH=/data/hombre.env PYTHONUNBUFFERED=1
USER hombre
EXPOSE 5000
CMD ["python", "app.py"]
