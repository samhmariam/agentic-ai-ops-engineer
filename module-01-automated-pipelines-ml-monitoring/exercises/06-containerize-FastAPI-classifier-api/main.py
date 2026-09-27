import io
import os
from contextlib import asynccontextmanager

import mlflow
import mlflow.transformers
from fastapi import FastAPI, File, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel

# Global dictionary to hold the model
models = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")
    model_name = os.getenv("MLFLOW_MODEL_NAME", "beans-disease-classifier")
    model_alias = os.getenv("MLFLOW_MODEL_ALIAS", "production")

    mlflow.set_tracking_uri(tracking_uri)
    model_uri = f"models:/{model_name}@{model_alias}"
    models["vit_model"] = mlflow.transformers.load_model(model_uri)

    try:
        models["vit_model"] = mlflow.transformers.load_model(model_uri)
        print(f"Model {model_name} loaded successfully.")
    except Exception as e:
        print(f"Error loading model: {e}")

    yield
    models.clear()


app = FastAPI(lifespan=lifespan)


class PredictionResponse(BaseModel):
    label: str
    score: float


@app.get("/health")
def health_check():
    if "vit_model" not in models:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return {"status": "ready"}


@app.post("/predict", response_model=PredictionResponse)
async def predict(file: UploadFile = File(...)):
    if "vit_model" not in models:
        raise HTTPException(status_code=503, detail="Model not loaded")

    request_object_content = await file.read()
    try:
        with Image.open(io.BytesIO(request_object_content)) as uploaded_image:
            image = uploaded_image.convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=400, detail="Invalid image file") from exc

    prediction = models["vit_model"](image)
    return PredictionResponse(
        label=prediction[0]["label"],
        score=prediction[0]["score"],
    )
