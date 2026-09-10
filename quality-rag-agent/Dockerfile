FROM python:3.11-slim

WORKDIR /app

COPY quality-rag-agent/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY shared ./shared
COPY data/docs ./data/docs
COPY quality-rag-agent ./quality-rag-agent

WORKDIR /app/quality-rag-agent
ENV DOCS_DIR=/app/data/docs
ENV PYTHONUNBUFFERED=1

EXPOSE 8001
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
