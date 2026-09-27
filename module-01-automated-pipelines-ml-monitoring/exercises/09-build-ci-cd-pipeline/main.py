import io

from fastapi import FastAPI, File, HTTPException, UploadFile
from PIL import Image
from transformers import pipeline

app = FastAPI(title="Beans Disease Classifier API")

MODEL_NAME = "nateraw/vit-base-beans"
classifier = pipeline("image-classification", model=MODEL_NAME)


@app.get("/health")
def health():
    return {"status": "healthy", "model": MODEL_NAME}


@app.post("/predict")
async def predict(file: UploadFile = File(...)):
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    contents = await file.read()
    image = Image.open(io.BytesIO(contents)).convert("RGB")
    predictions = classifier(image)

    return {"label": predictions[0]["label"], "score": predictions[0]["score"]}
