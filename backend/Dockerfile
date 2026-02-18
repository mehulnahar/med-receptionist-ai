FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=8000
CMD sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers ${UVICORN_WORKERS:-1} --proxy-headers --forwarded-allow-ips=*"
