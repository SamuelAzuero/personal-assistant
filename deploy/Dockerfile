# Multi-stage ultra-lightweight Dockerfile for Cloud Run Free Tier (<140MB)
# Stage 1: Build & Dependency Collection
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Minimal Runtime Image (<140MB)
FROM python:3.12-slim AS runner

WORKDIR /app

# Create non-root unprivileged service user for security
RUN groupadd -r appuser && useradd -r -u 1001 -g appuser appuser

# Copy installed Python packages from builder stage
COPY --from=builder /root/.local /home/appuser/.local

# Copy application source code and static dashboard assets
COPY app/ /app/app/

# Create persistent data directory and set permissions
RUN mkdir -p /app/data && chown -R appuser:appuser /app /home/appuser

# Switch to non-root user
USER appuser

# Environment configuration
ENV PATH="/home/appuser/.local/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    APP_ENV=production \
    DATABASE_PATH="/app/data/assistant.db"

EXPOSE 8080

# Health check probe
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request, os; urllib.request.urlopen('http://localhost:' + str(os.environ.get('PORT', 8080)) + '/health')" || exit 1

# Start FastAPI application with Uvicorn ASGI server
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]

