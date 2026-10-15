FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FASTEMBED_CACHE_DIR=/app/.fastembed

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# Download the embedding model at build time so the first request does not.
COPY src/embeddings.py src/embeddings.py
RUN touch src/__init__.py && python -c "from src.embeddings import MODEL_NAME; import os; from fastembed import TextEmbedding; TextEmbedding(model_name=MODEL_NAME, cache_dir=os.environ['FASTEMBED_CACHE_DIR'])"

COPY . .

# Render sets $PORT. Migrations and ingest are run separately (see README), not at boot.
CMD ["sh", "-c", "uvicorn src.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
