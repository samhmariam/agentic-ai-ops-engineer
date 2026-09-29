"""
Data Drift for textual data with Evidently AI.
"""

import json
import sys

import pandas as pd
from evidently.legacy.metrics import EmbeddingsDriftMetric
from evidently.legacy.metrics.data_drift.embedding_drift_methods import model
from evidently.legacy.pipeline.column_mapping import ColumnMapping
from evidently.legacy.report import Report
from sentence_transformers import SentenceTransformer


# NOTE: Download the datasets using the download_data script
REFERENCE_PATH = "data/reviews_2026_feb_nyc.csv"
CURRENT_PATH = "data/reviews_2026_feb_albany.csv"

# Keep encoding inexpensive and sampling reproducible.
SAMPLE_SIZE = 200

# Drift is detected when the domain classifier's ROC AUC exceeds this value.
EMBEDDING_THRESHOLD = 0.55


def load_reviews(path: str, n: int) -> list[str]:
    comments = pd.read_csv(path, usecols=["comments"])["comments"].dropna()
    comments = comments.astype(str).str.strip()
    comments = comments[comments.ne("")]
    if comments.empty:
        raise ValueError(f"No non-empty reviews found in {path}")
    return comments.sample(n=min(n, len(comments)), random_state=42).tolist()


print("Loading reviews...")
ref_comments = load_reviews(REFERENCE_PATH, SAMPLE_SIZE)
cur_comments = load_reviews(CURRENT_PATH, SAMPLE_SIZE)

print(f"Reference (NYC)   : {len(ref_comments)} reviews")
print(f"Current   (Albany): {len(cur_comments)} reviews")

print("\nEncoding reviews with paraphrase-multilingual-MiniLM-L12-v2...")
encoder = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

ref_embeddings = pd.DataFrame(encoder.encode(ref_comments, show_progress_bar=True))
ref_embeddings.columns = [f"col_{i}" for i in range(ref_embeddings.shape[1])]

cur_embeddings = pd.DataFrame(encoder.encode(cur_comments, show_progress_bar=True))
cur_embeddings.columns = [f"col_{i}" for i in range(cur_embeddings.shape[1])]


print("Running embedding drift report...")
column_mapping = ColumnMapping(
    embeddings={"review_embeddings": ref_embeddings.columns.tolist()}
)
report = Report(
    metrics=[
        EmbeddingsDriftMetric(
            embeddings_name="review_embeddings",
            drift_method=model(threshold=EMBEDDING_THRESHOLD),
        )
    ]
)
report.run(
    reference_data=ref_embeddings,
    current_data=cur_embeddings,
    column_mapping=column_mapping,
)
report.save_html("drift_report_text.html")

result = report.as_dict()["metrics"][0]["result"]
drift_score = result["drift_score"]
drift_detected = result["drift_detected"]
print(json.dumps({"drift_score": drift_score, "drift_detected": drift_detected}, indent=2))
print("Drift detected: gate failed." if drift_detected else "No drift detected: gate passed.")
sys.exit(1 if drift_detected else 0)
