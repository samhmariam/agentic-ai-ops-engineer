# Module 23 - Data Drift Detection with Evidently AI

## Overview

In this exercise you will detect semantic drift between two sets of Airbnb reviews using Evidently AI. Instead of comparing raw text, you will encode the reviews into embeddings and use Evidently to measure whether the semantic distribution has shifted between a reference dataset (NYC) and a current dataset (Albany).

---

## Setup

Download the datasets:

```bash
python download_data.py
```

This saves two CSV files to `data/`: NYC reviews (reference) and Albany reviews (current).

---

## 1. Complete `check_drift.py`

The script compares NYC and Albany Airbnb reviews by encoding them into sentence embeddings and measuring whether their semantic distributions differ. Complete the TODOs to load and encode the reviews, run the Evidently drift report, and implement a drift gate that exits with code 1 if drift is detected.

Read more: https://docs.evidentlyai.com/

---

## 2. Run the drift check

```bash
python check_drift.py
```

Open `drift_report_text.html` in your browser to inspect the full drift report.
