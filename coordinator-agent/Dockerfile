FROM python:3.11-slim

WORKDIR /app

COPY coordinator-agent/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY shared ./shared
COPY coordinator-agent ./coordinator-agent

WORKDIR /app/coordinator-agent
ENV PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
