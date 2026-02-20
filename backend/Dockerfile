FROM python:3.12-slim
WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as non-root user for security (principle of least privilege)
RUN adduser --disabled-password --no-create-home appuser && chown -R appuser:appuser /app
USER appuser

ENV PORT=8000

# Healthcheck so orchestrators (Docker Swarm, K8s) detect unresponsive instances
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
  CMD curl -f http://localhost:${PORT}/api/health || exit 1

CMD sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers ${UVICORN_WORKERS:-1} --proxy-headers --forwarded-allow-ips=*"
