FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1 \
    MLFLOW_TRACKING_URI=http://host.docker.internal:5000 \
    MLFLOW_MODEL_NAME=beans-disease-classifier \
    MLFLOW_MODEL_ALIAS=production

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
