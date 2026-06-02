#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from orbitlab.ml.artifact_registry import register_artifact


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Register a real AstroNet-family model artifact with SHA-256 metadata."
    )
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--mission", required=True, choices=["TESS", "Kepler", "K2"])
    parser.add_argument("--path", required=True, type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    artifact = register_artifact(
        model_id=args.model_id,
        mission=args.mission,
        path=args.path,
        source=args.source,
        version=args.version,
    )
    print(f"ORBITLAB_ASTRONET_MODEL_PATH={artifact.path}")
    print(f"ORBITLAB_ASTRONET_MODEL_SHA256={artifact.sha256}")
    print(f"ORBITLAB_ASTRONET_MODEL_SOURCE={artifact.source}")
    print(f"ORBITLAB_ASTRONET_MODEL_VERSION={artifact.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
