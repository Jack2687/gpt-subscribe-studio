FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/packages/contracts/src:/app/packages/core/src:/app/services/api/src:/app/services/orchestrator/src:/app/services/checkout/src:/app/services/payment/src:/app/services/account/src
WORKDIR /app
COPY deploy/server/requirements.txt /app/requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 dcp \
    && mkdir -p /data /config \
    && chown dcp:dcp /data /config \
    && node --version
COPY packages /app/packages
COPY services /app/services
COPY deploy/server/app.py /app/server.py
COPY deploy/server/login.html /app/login.html
COPY apps/web/dist /app/web
USER dcp
EXPOSE 8080
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log"]
