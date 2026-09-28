# Module 21 - API Monitoring with Prometheus and Grafana

## Overview

In this exercise you will instrument the Beans disease classifier API with Prometheus metrics. You will add custom metrics that track prediction confidence scores and per-class prediction counts, run the API with uvicorn, and verify the metrics endpoint directly in the workspace.

Running the full Prometheus + Grafana stack is optional and intended for local use only.


## 1. Complete `prometheus.yml`

Prometheus needs to know where to scrape metrics. Complete the configuration file so Prometheus scrapes the `/metrics` endpoint of the FastAPI app every 15 seconds.

---

## 2. Complete `main.py`

The API already serves predictions at `/predict`. You need to add Prometheus instrumentation.

**Add a Histogram** that tracks the distribution of prediction confidence scores per request. Use meaningful bucket boundaries between 0 and 1.

**Add a Counter** that tracks the number of predictions per output class, using the class name as a label.

**Instrument the FastAPI app** using `prometheus_fastapi_instrumentator` to automatically expose standard HTTP metrics (request count, latency) at `/metrics`. This is a different approach from the demo, which used a custom `@app.middleware("http")` to manually track these metrics. The instrumentator achieves the same result with less boilerplate.

**Inside `/predict`**: observe the confidence score in the histogram and increment the counter for the predicted class.

Read more: https://prometheus.github.io/client_python/

---

## 3. Verify metrics

Send a few requests to the API:

```bash
curl -X POST http://localhost:8000/predict -F "file=@<your-image.jpg>"
```

Then check that your custom metrics appear at `http://localhost:8000/metrics`. Look for `model_prediction_confidence` and `model_prediction_class_total`.

---

## (Optional) Run the full stack locally with Docker Compose

> Please **DO NOT** run Docker Compose inside the student workspace.
> These steps are for local use only.

`docker-compose.yml` starts three services together:
- **beans-api** (port 8000): the FastAPI inference server
- **Prometheus** (port 9090): scrapes metrics from the API
- **Grafana** (port 3000): visualizes metrics from Prometheus

```bash
docker-compose up --build
```

Once running, open Grafana at http://localhost:3000 (login: admin / admin):
- Add Prometheus as a data source (URL: `http://prometheus:9090`)
- Create a dashboard with panels for request rate, confidence distribution, and prediction counts per class
