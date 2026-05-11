#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from orbitlab.ml.artifact_registry import KEPLER_ASTRONET_MODEL_ID, register_artifact


COMMIT = "9809ce92306f11fbdc96f9830b522026710a3883"
OWNER = "bibinthomas123"
REPO = "Astronet"
BASE_MEDIA_URL = f"https://media.githubusercontent.com/media/{OWNER}/{REPO}/{COMMIT}"
CHECKPOINT_DIR = "exoplanet-ml/model"
CHECKPOINT_FILES = {
    "model.ckpt-20000.data-00000-of-00001": "11ba42b970063eea55cda7f44cd3d2e6949e1132567d0b0c9f9341a93de4415a",
    "model.ckpt-20000.index": "e79831908735fb6c6dce8ace2f7133c3ad626ce77fcc91ce0c8b443e5cb2737c",
    "model.ckpt-20000.meta": "d8ab00670a58edd49667143ef1e28d7f43a2281c627d73c45ad413dfdc9a5031",
}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def reject_lfs_pointer(payload: bytes, name: str) -> None:
    prefix = payload[:128].decode("utf-8", errors="ignore")
    if prefix.startswith("version https://git-lfs.github.com/spec/v1"):
        raise ValueError(f"{name} resolved to a Git LFS pointer instead of checkpoint bytes")


def download_file(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "OrbitLab artifact fetcher"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def fetch_checkpoint(output_dir: Path, *, remote_dir: str = CHECKPOINT_DIR) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for filename, expected_hash in CHECKPOINT_FILES.items():
        remote_path = f"{remote_dir.strip('/')}/{filename}" if remote_dir else filename
        payload = download_file(f"{BASE_MEDIA_URL}/{remote_path}")
        reject_lfs_pointer(payload, filename)
        actual_hash = sha256_bytes(payload)
        if actual_hash.lower() != expected_hash.lower():
            raise ValueError(f"{filename} SHA-256 mismatch: expected {expected_hash}, got {actual_hash}")
        target = output_dir / filename
        target.write_bytes(payload)
        written.append(target)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch and register the pinned Kepler AstroNet checkpoint.")
    parser.add_argument("--output-dir", type=Path, default=Path(".orbitlab/models/kepler-astronet-checkpoint"))
    parser.add_argument(
        "--remote-dir",
        default=CHECKPOINT_DIR,
        help="Repository directory containing model.ckpt.* files if they are not at the repository root.",
    )
    args = parser.parse_args()
    fetch_checkpoint(args.output_dir, remote_dir=args.remote_dir)
    artifact = register_artifact(
        model_id=KEPLER_ASTRONET_MODEL_ID,
        mission="Kepler",
        path=args.output_dir,
        source=f"{OWNER}/{REPO} TensorFlow checkpoint at {COMMIT}",
        version=COMMIT,
    )
    print(f"registered {artifact.model_id}")
    print(f"path={artifact.path}")
    print(f"sha256={artifact.sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
