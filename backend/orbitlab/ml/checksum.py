from __future__ import annotations

import hashlib
from pathlib import Path

from orbitlab.exceptions import ModelArtifactError


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_dir():
        files = sorted(p for p in path.rglob("*") if p.is_file())
        if not files:
            raise ModelArtifactError(f"model directory is empty: {path}")
        for file_path in files:
            digest.update(str(file_path.relative_to(path)).encode("utf-8"))
            with open(file_path, "rb") as f:
                while chunk := f.read(65536):
                    digest.update(chunk)
    else:
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                digest.update(chunk)
    return digest.hexdigest()

