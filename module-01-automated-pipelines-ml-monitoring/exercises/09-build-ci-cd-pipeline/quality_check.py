"""
Deepchecks quality check for the beans ViT model.
"""

import sys

import numpy as np
from datasets import load_dataset
from deepchecks.core import CheckFailure
from deepchecks.vision import VisionData
from deepchecks.vision.suites import train_test_validation
from deepchecks.vision.vision_data import BatchOutputFormat
from torch.utils.data import DataLoader
from torch.utils.data import Dataset as TorchDataset
from transformers import pipeline

MODEL_NAME = "nateraw/vit-base-beans"


class BeansDataset(TorchDataset):
    def __init__(self, hf_dataset):
        self.dataset = hf_dataset

    def __len__(self):
        return len(self.dataset)

    def __getitem__(self, idx):
        return self.dataset[idx]


def make_collate_fn(pipe, label_names):
    def collate_fn(examples):
        images_pil = [ex["image"].convert("RGB") for ex in examples]
        labels = [ex["labels"] for ex in examples]
        predictions_raw = pipe(images_pil)
        proba = []
        for preds in predictions_raw:
            scores = {p["label"]: p["score"] for p in preds}
            proba.append([scores.get(lbl, 0.0) for lbl in label_names])
        images_np = [np.array(img) for img in images_pil]
        return BatchOutputFormat(images=images_np, labels=labels, predictions=proba)
    return collate_fn


def build_vision_data(hf_split, pipe, label_names):
    dataset = BeansDataset(load_dataset("beans", split=hf_split))
    label_map = {i: lbl for i, lbl in enumerate(label_names)}
    loader = DataLoader(
        dataset,
        batch_size=8,
        collate_fn=make_collate_fn(pipe, label_names),
    )
    return VisionData(batch_loader=loader, task_type="classification", label_map=label_map)


def main():
    print(f"Loading model: {MODEL_NAME}...")
    pipe = pipeline("image-classification", model=MODEL_NAME)

    dataset = load_dataset("beans", split="validation")
    label_names = dataset.features["labels"].names

    print("Building VisionData...")
    train_data = build_vision_data("train", pipe, label_names)
    test_data = build_vision_data("test", pipe, label_names)

    print("Running Deepchecks suite...")
    suite = train_test_validation()
    result = suite.run(train_data, test_data, max_samples=500)

    print(f"{len(result.results)} checks executed.")

    for check_result in result.results:
        if isinstance(check_result, CheckFailure):
            continue
        if check_result.check.name() == "Label Drift":
            drift_score = check_result.value["Samples Per Class"]["Drift score"]
            if drift_score > 0.5:
                print(f"  [FAIL] Label Drift: score {drift_score:.3f} exceeds threshold 0.5")
                sys.exit(1)
            else:
                print(f"  [PASS] Label Drift: score {drift_score:.3f} ≤ 0.5")
            break

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
