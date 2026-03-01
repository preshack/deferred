# === Stage 1: Builder ===
FROM python:3.11-slim AS builder

WORKDIR /build
COPY pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install .

# === Stage 2: Runtime ===
FROM python:3.11-slim AS runtime

# Security: non-root user
RUN groupadd -r deferred && useradd -r -g deferred deferred

WORKDIR /app
COPY --from=builder /install /usr/local
COPY . .

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()"

USER deferred
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
