# Module 27 - Fairness Evaluation with Fairlearn

## Overview

In this exercise you will evaluate a hospital readmission classifier for fairness across demographic groups. You will train the model, then use Fairlearn's `MetricFrame` to measure accuracy, precision, and recall broken down by gender, and implement a fairness gate that blocks promotion if demographic parity difference or equalized odds difference exceed defined thresholds.


## 1. Complete and run `train.py`

Complete the TODOs in `train.py` to prepare the dataset before training. The model training and saving logic is already provided.

```bash
python train.py
```

This produces: `model.joblib`, `X_test.npy`, `y_test.npy`, `sf_test.csv`.

---

## 2. Complete `check_fairness.py`

Complete the TODOs to load the trained model, evaluate fairness across gender subgroups, and implement the fairness gate. 

Read more: https://fairlearn.org/main/user_guide/

---

## 3. Run the fairness check

```bash
python check_fairness.py
```

