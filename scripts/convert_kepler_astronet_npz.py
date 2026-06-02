#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from orbitlab.ml.artifact_registry import KEPLER_ASTRONET_MODEL_ID, register_artifact


def docker_available() -> bool:
    return shutil.which("docker") is not None


def run_docker_conversion(checkpoint_dir: Path, output_npz: Path, image: str) -> None:
    if not docker_available():
        raise RuntimeError("Docker is required for TensorFlow checkpoint conversion on this machine")
    output_npz.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{checkpoint_dir.resolve()}:/checkpoint:ro",
        "-v",
        f"{output_npz.parent.resolve()}:/out",
        image,
        "python",
        "/converter/export_orbitlab_npz.py",
        "--checkpoint-dir",
        "/checkpoint",
        "--output",
        f"/out/{output_npz.name}",
    ]
    subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Convert the pinned Kepler AstroNet checkpoint to an OrbitLab NumPy NPZ. "
            "Requires a converter Docker image that provides /converter/export_orbitlab_npz.py."
        )
    )
    parser.add_argument("--checkpoint-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(".orbitlab/models/kepler-astronet.npz"))
    parser.add_argument("--image", default="orbitlab/astronet-converter:tf1")
    args = parser.parse_args()
    run_docker_conversion(args.checkpoint_dir, args.output, args.image)
    artifact = register_artifact(
        model_id=KEPLER_ASTRONET_MODEL_ID,
        mission="Kepler",
        path=args.output,
        source="Converted from bibinthomas123/Astronet TensorFlow checkpoint",
        version="orbitlab-numpy",
    )
    print(f"registered {artifact.model_id}")
    print(f"path={artifact.path}")
    print(f"sha256={artifact.sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
