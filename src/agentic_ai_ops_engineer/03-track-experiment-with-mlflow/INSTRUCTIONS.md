# Module 07 — Experiment Tracking with MLflow

In this exercise you will instrument a FinBERT fine-tuning script with MLflow tracking, compare multiple training runs in the MLflow UI, and programmatically retrieve the best run.

---

## 1. Start the MLflow tracking server

Before running any training, start the MLflow server locally.

```bash
mlflow server --host 127.0.0.1 --port 5000
```

Leave this running in a separate terminal. All runs will be logged to `http://127.0.0.1:5000`, which matches the `tracking_uri` in `params.yaml`.

---

## 2. Understand the training script

Open `train.py`. The script fine-tunes FinBERT on a financial sentiment dataset using the HuggingFace `Trainer`.

MLflow tracking is wired through a custom `MLflowCallback` that hooks into the `Trainer` lifecycle. The class skeleton is provided, you need to implement each method.

HuggingFace `TrainerCallback` exposes these hooks:
- `on_train_begin`: called at the beginning of the training
- `on_epoch_end`: called at the end of each epoch
- `on_evaluate`: called after each evaluation pass
- `on_train_end`: called at the end of the training

---

## 3. Complete the MLflow callback

Implement the four methods in `MLflowCallback`.

Read more about MLflow tracking: https://mlflow.org/docs/latest/tracking.html
Read more about HF callbacks: https://huggingface.co/docs/transformers/en/main_classes/callback#transformers.TrainerCallback

---

## 4. Run training at least three times with different hyperparameters

Edit `params.yaml` between runs to vary the hyperparameters. For example:

| Run | learning_rate | batch_size | num_epochs |
|-----|--------------|------------|------------|
| 1   | 2e-5         | 16         | 3          |
| 2   | 5e-5         | 16         | 3          |
| 3   | 2e-5         | 8          | 5          |

```bash
python train.py
```

Each run is recorded separately in the MLflow experiment with its own parameters, metrics, and model artifact.

---

## 5. Compare runs in the MLflow UI

Open the MLflow UI in your browser:

```
http://127.0.0.1:5000
```

Navigate to the `finbert-financial-sentiment` experiment. Select multiple runs and use the **Compare** view to plot metrics side-by-side across runs. This lets you visually identify which hyperparameter combination yields the best validation accuracy.

---

## 6. Retrieve the best run programmatically

Complete `best_run.py` to query the experiment and retrieve the best run without using the UI.

```bash
python best_run.py
```

The script will print the run ID, status, all logged parameters, metrics, and custom tags for the best run.
