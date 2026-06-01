# syntax=docker/dockerfile:1.6
# Roma ERP — production container.
# Build:    docker build -t roma-erp .
# Run:      docker compose up -d

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# OS deps: libpq for psycopg, fonts for Arabic PDF/print rendering
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
        fonts-noto fonts-noto-cjk \
        ca-certificates \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Africa/Cairo

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App source
COPY . .

# Collect static files at build time (used by WhiteNoise at runtime)
RUN DJANGO_DEBUG=False \
    DJANGO_SECRET_KEY=build-time-placeholder \
    DJANGO_ALLOWED_HOSTS=localhost \
    DATABASE_URL=sqlite:///tmp/build.sqlite3 \
    python manage.py collectstatic --noinput

EXPOSE 8000

# Default command — overridden in docker-compose for clarity
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
