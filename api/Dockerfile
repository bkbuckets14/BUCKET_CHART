FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Production command (no --reload). docker-compose.yml overrides this with
# --reload for local development.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
