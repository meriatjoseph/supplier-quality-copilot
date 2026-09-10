FROM python:3.11-slim

WORKDIR /app

COPY traceability-agent/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY shared ./shared
COPY data/manufacturing ./data/manufacturing
COPY traceability-agent ./traceability-agent

WORKDIR /app/traceability-agent
ENV MANUFACTURING_DB_PATH=/app/data/manufacturing/manufacturing.db
ENV PYTHONUNBUFFERED=1

EXPOSE 8002
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8002"]
