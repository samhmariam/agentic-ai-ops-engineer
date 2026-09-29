# Module 25 - Model Explainability with SHAP

## Overview

In this exercise you will build an explainability API for a text emotion classifier using SHAP. The API exposes three endpoints: `/predict` for standard inference, `/explain` for token-level SHAP values across all emotion labels, and `/predict-explain` for combined prediction and explanation for the top label.


## 1. Complete `main.py`

The API wraps a text emotion classifier with SHAP-based explainability. Complete the TODOs to initialize the SHAP explainer at startup, implement the core explanation logic, and add the `/explain` and `/predict-explain` endpoints.

Read more: https://shap.readthedocs.io/en/latest/

---

## 2. Test the endpoints

```bash
# Standard prediction
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"text": "I am so happy today!"}'

# Token-level explanation for all labels
curl -X POST http://localhost:8000/explain \
  -H "Content-Type: application/json" \
  -d '{"text": "I am so happy today!"}'

# Combined prediction and explanation
curl -X POST http://localhost:8000/predict-explain \
  -H "Content-Type: application/json" \
  -d '{"text": "I am so happy today!"}'
```

