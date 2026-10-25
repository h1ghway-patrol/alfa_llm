FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    USE_DB=true \
    DB_PATH=/app/data/app.db \
    SEED_DIR=/seed \
    LLM_PROVIDER=fake \
    APP_ENV=local

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home-dir /app app

COPY requirements.txt requirements-core.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-core.txt

COPY app ./app
COPY scripts ./scripts
COPY frontend ./frontend
COPY tests/data ./tests/data
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN mkdir -p /app/data /seed \
    && chown -R app:app /app/data \
    && chmod +x /usr/local/bin/entrypoint.sh

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
