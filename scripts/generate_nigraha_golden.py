#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate compact Nigraha golden outputs in the original Keras runtime. "
            "Requires a Docker image with the original runtime and scripts/original_nigraha_forward.py."
        )
    )
    parser.add_argument("--output", type=Path, default=Path("backend/tests/fixtures/nigraha_golden_model1.json"))
    parser.add_argument("--image", default="orbitlab/nigraha-keras:tf2")
    args = parser.parse_args()
    if shutil.which("docker") is None:
        raise RuntimeError("Docker is required to generate original-Keras Nigraha golden outputs")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{Path.cwd().resolve()}:/workspace",
        "-w",
        "/workspace",
        args.image,
        "python",
        "/workspace/scripts/original_nigraha_forward.py",
        "--output",
        f"/workspace/{args.output}",
    ]
    subprocess.run(command, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
