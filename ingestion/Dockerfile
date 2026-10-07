FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Nightly update by default. Run the one-time backfill with:
#   docker compose run --rm ingestion python ingest_v2.py
CMD ["python", "ingest_update.py"]
