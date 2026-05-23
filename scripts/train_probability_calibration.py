#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def _load_csv(
    path: Path, score_column: str, label_column: str, positive_labels: set[str]
) -> tuple[np.ndarray, np.ndarray]:
    import pandas as pd

    frame = pd.read_csv(path)
    if score_column not in frame.columns:
        raise KeyError(f"missing score column {score_column!r}; available: {', '.join(frame.columns)}")
    if label_column not in frame.columns:
        raise KeyError(f"missing label column {label_column!r}; available: {', '.join(frame.columns)}")
    scores = pd.to_numeric(frame[score_column], errors="coerce")
    labels = frame[label_column].astype(str).str.strip().str.lower().isin({label.lower() for label in positive_labels})
    mask = scores.notna() & frame[label_column].notna()
    x = scores[mask].to_numpy(dtype=float)
    y = labels[mask].astype(int).to_numpy(dtype=int)
    if np.nanmax(x) > 1.0:
        x = x / 100.0
    x = np.clip(x, 0.0, 1.0)
    if np.unique(y).size < 2:
        raise RuntimeError("calibration labels need both positive and negative examples")
    return x, y


def train(
    input_path: Path, output_path: Path, mission: str, score_column: str, label_column: str, positive_labels: set[str]
) -> None:
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression

    x, y = _load_csv(input_path, score_column, label_column, positive_labels)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if x.size >= 200:
        model = IsotonicRegression(out_of_bounds="clip")
        model.fit(x, y)
        grid = np.linspace(0.0, 1.0, 101)
        payload = {
            "mission": mission.upper(),
            "method": "isotonic_bins",
            "source": str(input_path),
            "score_column": score_column,
            "label_column": label_column,
            "positive_labels": sorted(positive_labels),
            "sample_count": int(x.size),
            "x": grid.tolist(),
            "y": np.clip(model.predict(grid), 0.0, 1.0).astype(float).tolist(),
        }
    else:
        model = LogisticRegression(solver="lbfgs")
        model.fit(x.reshape(-1, 1), y)
        payload = {
            "mission": mission.upper(),
            "method": "sigmoid",
            "source": str(input_path),
            "score_column": score_column,
            "label_column": label_column,
            "positive_labels": sorted(positive_labels),
            "sample_count": int(x.size),
            "coef": float(model.coef_.reshape(-1)[0]),
            "intercept": float(model.intercept_.reshape(-1)[0]),
        }
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train an OrbitLab mission probability calibration bundle.")
    parser.add_argument("mission", choices=["tess", "kepler", "k2"])
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--score-column", required=True)
    parser.add_argument("--label-column", required=True)
    parser.add_argument("--positive-label", action="append", default=[])
    args = parser.parse_args()
    positive = set(args.positive_label or ["PC", "KP", "CONFIRMED", "KNOWN PLANET", "PLANET CANDIDATE"])
    output = args.output or Path(f".orbitlab/models/calibration/{args.mission}-probability-calibration.json")
    train(args.input, output, args.mission, args.score_column, args.label_column, positive)


if __name__ == "__main__":
    main()
