FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    DATABASE_PATH=/app/data/rag.db

WORKDIR /app
COPY pyproject.toml README.md ./
COPY app app
COPY api api
COPY agent agent
COPY ingestion ingestion
COPY retrieval retrieval
COPY frontend frontend
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
