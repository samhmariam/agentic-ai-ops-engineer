# Module 11 — Model Registry with MLflow

## Overview

The MLflow Model Registry is a centralized store for managing the lifecycle of ML models. It allows you to register models produced by training runs, assign version numbers, and promote specific versions to named stages so downstream systems always load the right model.

In this exercise, you are given a pre-trained Visual Transformer model fine-tuned on the beans plant disease dataset (`nateraw/vit-base-beans`) and an `evaluate.py` script. Your tasks are to register the model in the MLflow Model Registry, promote it to production, and write a `predict.py` script that dynamically loads the production model from the registry and runs inference.

---

## Setup

Start the MLflow tracking server:

```bash
mlflow server --host 127.0.0.1 --port 5000
```

---

## 1. Complete and run `evaluate.py`

The evaluation script is mostly provided. It loads the pre-trained ViT pipeline, runs inference on the test split, and logs accuracy to MLflow.

You need to complete two steps inside the active run:

- **Register the model**: log the HuggingFace pipeline as an MLflow artifact and register it under the name defined in `params.yaml`.
- **Promote to production**: if accuracy exceeds the threshold in `params.yaml`, assign the `production` alias to this model version using the MLflow client.

```bash
python evaluate.py
```

Open the MLflow UI at [http://localhost:5000](http://localhost:5000) and verify:
- The `beans-vit-classification` experiment contains a run with `accuracy` logged
- The Model Registry contains a new model version with the `production` alias assigned

Read more: https://mlflow.org/docs/latest/ml/model-registry/tutorial/

---

## 2. Complete `predict.py`

`predict.py` loads the production model directly from the registry by alias and runs inference on a sample image.


```bash
python predict.py
```

You can also pass a custom image:

```bash
python predict.py --image path/to/image.jpg
```