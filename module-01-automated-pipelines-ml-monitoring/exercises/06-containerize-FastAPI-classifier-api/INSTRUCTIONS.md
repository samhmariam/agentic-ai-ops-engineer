# Module 13 — Containerizing an ML API with Docker

## Overview

In this exercise you will package the beans disease classifier from module 11 into a production-ready Docker container. The container runs a FastAPI inference app that loads the model from the MLflow registry at startup and exposes two endpoints: a health check and a `/predict` endpoint that accepts an image and returns the predicted label and confidence score.


## Prerequisites

Make sure the MLflow server is running and the `beans-disease-classifier` model is registered and promoted to the `production` alias. If not, run `evaluate.py` first:

```bash
mlflow server --host 0.0.0.0 --port 5000 --allowed-hosts host.docker.internal,localhost,127.0.0.1
python evaluate.py
```

## 1. Complete `main.py`

The FastAPI application loads the model once at startup using the [lifespan](https://fastapi.tiangolo.com/advanced/events/) context manager and stores it in the global `models` dict. The model URI and tracking URI are read from environment variables so they can be configured at runtime without changing the code.

Implement the `/health` and `/predict` endpoints.


## 2. Write the Dockerfile and `.dockerignore`

The Dockerfile packages the app and its dependencies into a self-contained image.

Also create a `.dockerignore` file to exclude files that should not be copied into the image (e.g., `evaluate.py`, `__pycache__`, and `*.pyc`). A `.dockerignore` works like `.gitignore`: each line is a pattern Docker excludes from the build context.

Read more about Dockerfile best practices: https://docs.docker.com/build/building/best-practices/



## 3. Build the Docker image

```bash
docker build -t beans-api .
```


## 4. Test your FastAPI service

> Please **DO NOT** run the docker container inside the student workspace.
> These steps are for information only and can be tested locally.

```bash
# Run the container
docker run -p 8000:8000 --add-host=host.docker.internal:host-gateway -e MLFLOW_TRACKING_URI="http://host.docker.internal:5000" beans-api
```

Verify the server is up:

```bash
curl http://localhost:8000/health
```

Test the `/predict` endpoint:

```bash
curl -X POST http://localhost:8000/predict \
  -F "file=@test-image.jpg"
```
