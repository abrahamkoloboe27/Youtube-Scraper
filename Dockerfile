# Dockerfile pour le scraper YouTube avec MongoDB et Minio
FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install uv \
    && uv pip install --no-cache-dir -r requirements.txt --system

# Installation Playwright et dépendances
RUN apt-get update && apt-get install -y wget gnupg && \
    pip install playwright && \
    playwright install --with-deps chromium

COPY . .

CMD ["python", "scraper.py"]