
import io
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from PIL import Image
from prometheus_client import Counter, Histogram
from prometheus_fastapi_instrumentator import Instrumentator
from transformers import pipeline

prediction_confidence = Histogram(
    "prediction_confidence",
    "Confidence scores of top model predictions",
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)

prediction_class_counter = Counter(
    "prediction_class_counter",
    "Number of predictions per output class",
    labelnames=("label",),
)

MODEL_NAME = "nateraw/vit-base-beans"
classifier = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global classifier
    print(f"Loading model: {MODEL_NAME}...")
    classifier = pipeline("image-classification", model=MODEL_NAME)
    print("Model loaded.")
    yield
    classifier = None


app = FastAPI(title="Beans Disease Classifier API", lifespan=lifespan)

Instrumentator().instrument(app).expose(app)


@app.get("/health")
def health():
    return {"status": "healthy" if classifier else "loading", "model": MODEL_NAME}


@app.post("/predict")
async def predict(file: UploadFile = File(...)):
    if classifier is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    contents = await file.read()
    image = Image.open(io.BytesIO(contents)).convert("RGB")
    predictions = classifier(image)

    top_prediction = max(predictions, key=lambda prediction: prediction["score"])
    label = top_prediction["label"]
    score = top_prediction["score"]

    prediction_confidence.observe(score)
    prediction_class_counter.labels(label=label).inc()

    return {"label": label, "score": score}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
