# Module 09 — Continuous Training with Prefect

Prefect is an open-source workflow orchestration tool. In this exercise you will build a continuous training pipeline that automatically retrains a PyTorch MLP whenever new sales data arrives, compares the new model against the best previous model, and saves it only if it improves.


## Setup

Start three services in separate terminals before running anything:

```bash
# Terminal 1 — MLflow tracking server
mlflow server --host 127.0.0.1 --port 5000

# Terminal 2 — Prefect server
prefect server start

# Terminal 3 — Prefect worker
PREFECT_API_URL=http://127.0.0.1:4200/api python -m prefect worker start --pool default
```


## 1. Understand `add_data.py`

This script simulates new data arriving over time. Each call appends the next data chunk to `data/train.csv` and emits a Prefect event called `new-data-available`. The pipeline is triggered by that event.

Run it once to initialize the training data:

```bash
python add_data.py
```


## 2. Understand `train.py`

The training script is fully provided. It trains a PyTorch MLP on `data/train.csv`, logs hyperparameters and metrics to MLflow, and saves the trained model to `outputs/model_candidate.pt`.

You do not need to modify this file.


## 3. Complete `validate.py`

`validate.py` compares the most recent MLflow run (the challenger) against all previous runs (the champion) to decide whether the new model should be promoted.


## 4. Complete `flow.py`

`flow.py` defines the full continuous training workflow using Prefect.

Read more about Prefect flows and tasks: https://docs.prefect.io/latest/concepts/flows/

---

## 5. Register the deployment

Once `flow.py` is complete, register it with the local Prefect server:

```bash
python flow.py
```

You should see:

```
Your flow 'continuous-training-flow' is being served and polling for scheduled runs!
```

Leave this running. The deployment now listens for `new-data-available` events.


## 6. Trigger the pipeline

In a separate terminal, run `add_data.py` to append the next data chunk and fire the event:

```bash
python add_data.py
```

Prefect will automatically start a flow run. Monitor it in the Prefect UI at [http://localhost:4200](http://localhost:4200) and verify the MLflow run at [http://localhost:5000](http://localhost:5000).

Run `add_data.py` multiple times to simulate continuous data arrival and observe how the model is retrained and compared each time.