# SemLift container: React UI built in stage 1, FastAPI + pipeline in stage 2.
# Runs inside the client tenant (Snowpark Container Services or a client VPC); inputs never leave it.
FROM node:22-slim AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY ui/ ./
RUN npm run build

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY semlift ./semlift
RUN pip install --no-cache-dir ".[snowflake]"
COPY config ./config
COPY --from=ui /ui/dist ./ui/dist
ENV SEMLIFT_WORKSPACE=/data/workspace \
    SEMLIFT_CONFIG_DIR=/app/config \
    SEMLIFT_UI_DIST=/app/ui/dist \
    SEMLIFT_ENV=production
VOLUME ["/data"]
EXPOSE 8000
RUN useradd -m semlift && mkdir -p /data && chown semlift /data
USER semlift
CMD ["semlift", "-w", "/data/workspace", "serve", "--host", "0.0.0.0", "--port", "8000"]
