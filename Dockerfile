FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements-dev.txt .
COPY requirements-core.txt .

RUN pip install --no-cache-dir -r requirements-dev.txt -r requirements-core.txt

COPY app ./app
COPY scripts ./scripts
COPY data ./data

COPY frontend/index.html /usr/share/nginx/html/index.html
COPY frontend/styles.css /usr/share/nginx/html/styles.css
COPY frontend/nginx.conf /etc/nginx/sites-available/default
COPY docker-entrypoint.sh /docker-entrypoint.sh

RUN chmod +x /docker-entrypoint.sh     && rm -f /etc/nginx/sites-enabled/default     && ln -s /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default

EXPOSE 80

CMD ["/docker-entrypoint.sh"]
