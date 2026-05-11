#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from orbitlab.ml.artifact_registry import K2_EXOMAC_MODEL_ID, register_artifact

REPO = "ZapatoProgramming/ExoMAC-KKT"
REVISION = "5cda5310d5a163679c6915f9463a4d6afc312483"
BASE_URL = f"https://huggingface.co/{REPO}/resolve/{REVISION}"
SOURCE = "ZapatoProgramming/ExoMAC-KKT pretrained NASA Kepler/K2/TESS catalog classifier"

FILES = {
    "exoplanet_best_model.joblib": "dc00adc2ae9fc7c69d5ee9e0710ee4773547afb7feabb8f735fa622e351aee34",
    "exoplanet_feature_columns.json": "7795bd069273e8b4b2e0b3c4f414bb4895abd4bde1cf0905e3d96b3e62474f7b",
    "exoplanet_class_labels.json": "685307cb6cc555e78483c901e981d2d0d24de6ff9ee5b14ed5c43f459c940449",
    "exoplanet_metadata.json": "323066eac52e183dc5aa85a554959474c217b1605d2d01b95fde17cdcb45ea44",
}

EXPECTED_FEATURES = [
    "koi_depth",
    "koi_duration",
    "koi_impact",
    "koi_period",
    "koi_prad",
    "koi_slogg",
    "koi_sma",
    "koi_smet",
    "koi_snr",
    "koi_srad",
    "koi_steff",
    "duty_cycle",
    "log_koi_period",
    "log_koi_depth",
    "log_koi_snr",
    "teq_proxy",
]


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def download_file(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "OrbitLab/0.1"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def fetch_bundle(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, expected_sha256 in FILES.items():
        payload = download_file(f"{BASE_URL}/{name}")
        actual_sha256 = sha256_bytes(payload)
        if actual_sha256.lower() != expected_sha256.lower():
            raise ValueError(f"checksum mismatch for {name}: expected {expected_sha256}, got {actual_sha256}")
        path = output_dir / name
        path.write_bytes(payload)
        written.append(path)

    features = json.loads((output_dir / "exoplanet_feature_columns.json").read_text())
    labels = json.loads((output_dir / "exoplanet_class_labels.json").read_text())
    metadata = json.loads((output_dir / "exoplanet_metadata.json").read_text())
    if features != EXPECTED_FEATURES:
        raise ValueError("downloaded ExoMAC feature schema does not match the integrated OrbitLab mapper")
    if labels != ["CANDIDATE", "CONFIRMED", "FALSE POSITIVE"]:
        raise ValueError("downloaded ExoMAC label schema does not match OrbitLab expectations")
    if metadata.get("best_model_name") != "RandomForest":
        raise ValueError("downloaded ExoMAC artifact is not the expected RandomForest model")
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch and register the K2-capable ExoMAC-KKT pretrained model.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".orbitlab/models/k2-exomac-kkt-randomforest"),
    )
    parser.add_argument("--no-register", action="store_true")
    args = parser.parse_args()

    output_dir = args.output_dir.expanduser().resolve()
    written = fetch_bundle(output_dir)
    print(f"fetched {len(written)} ExoMAC-KKT files into {output_dir}")
    if not args.no_register:
        artifact = register_artifact(
            model_id=K2_EXOMAC_MODEL_ID,
            mission="K2",
            path=output_dir,
            source=SOURCE,
            version=REVISION,
        )
        print(f"registered {artifact.model_id}")
        print(f"ORBITLAB_MODEL_REGISTRY entry checksum={artifact.sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
