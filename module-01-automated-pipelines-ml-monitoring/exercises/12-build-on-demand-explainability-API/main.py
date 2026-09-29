"""
On-demand explainability API using SHAP.
"""

from contextlib import asynccontextmanager

import shap
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from transformers import pipeline

MODEL_NAME = "nateraw/bert-base-uncased-emotion"

pipe = None
explainer = None
label_names = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pipe, explainer, label_names
    print(f"Loading model: {MODEL_NAME}...")
    pipe = pipeline("text-classification", model=MODEL_NAME, top_k=None)
    label_names = [pipe.model.config.id2label[i] for i in range(len(pipe.model.config.id2label))]
    print("Initializing SHAP explainer...")
    explainer = shap.Explainer(pipe)

    yield
    pipe = None
    explainer = None
    label_names = None


app = FastAPI(title="Emotion Explainability API", lifespan=lifespan)


class TextRequest(BaseModel):
    text: str


def _run_shap(text: str) -> dict:
    if explainer is None or label_names is None:
        raise HTTPException(status_code=503, detail="Explainer not loaded")
    explanation = explainer([text])[0]
    return {
        "tokens": explanation.data.tolist(),
        "shap_values": {
            label: explanation.values[:, i].tolist()
            for i, label in enumerate(label_names)
        },
    }


@app.get("/health")
def health():
    return {"status": "healthy" if pipe else "loading", "model": MODEL_NAME}


@app.post("/predict")
def predict(request: TextRequest):
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")
    return {"predictions": pipe(request.text)[0]}


@app.post("/explain")
def explain(request: TextRequest):
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")
    return _run_shap(request.text)


@app.post("/predict-explain")
def predict_explain(request: TextRequest):
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")
    if pipe is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    predictions = pipe([request.text])[0]
    top_label = max(predictions, key=lambda prediction: prediction["score"])["label"]
    explanation = _run_shap(request.text)
    return {
        "predictions": predictions,
        "top_label": top_label,
        "tokens": explanation["tokens"],
        "shap_values": {top_label: explanation["shap_values"][top_label]},
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
