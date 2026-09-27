# Module 15 - Model Quality Gate with Deepchecks

## Overview

In this exercise you will extend the automated training pipeline by adding a model quality gate. Before a new model is promoted to `@production`, two validation steps must pass:

1. **Champion/challenger**: the new `@dev` model must outperform the current `@production` model on validation accuracy.
2. **Quality gate**: Deepchecks must confirm the model produces well-calibrated predictions with no significant label drift between train and test sets.

---

## Setup

Start the MLflow tracking server:

```bash
mlflow server --host 127.0.0.1 --port 5000
```

---

## 1. Understand the pipeline

Open `flow.py`. The pipeline runs three Prefect tasks in order:

- **Train**: fine-tunes the ViT model on the beans dataset and registers it under the `@dev` alias.
- **Validate**: runs champion/challenger comparison and Deepchecks quality checks. Only returns `True` if both pass.
- **Promote**: assigns the `@production` alias to `@dev` if validation passed.

You do not need to modify `flow.py` or `train.py`.

---

## 2. Complete `validate.py`

The champion/challenger logic is already implemented in `champion_challenger()`. You need to complete the Deepchecks quality gate in `run_quality_checks()`.

Read more about Deepchecks VisionData: https://docs.deepchecks.com/stable/vision/usage_guides/visiondata_object.html  
Read more about the train/test validation suite: https://docs.deepchecks.com/stable/api/generated/deepchecks.vision.suites.train_test_validation.html

---

## 3. Run the pipeline

```bash
python flow.py
```

The pipeline will train the model, run validation (champion/challenger + Deepchecks), and promote to `@production` only if both checks pass.