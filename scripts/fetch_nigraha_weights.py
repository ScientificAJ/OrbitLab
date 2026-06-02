#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from orbitlab.ml.artifact_registry import register_artifact

COMMIT = "c4365b41dd02b187c3210189ffe8e3ead584f4f5"
BASE_URL = f"https://raw.githubusercontent.com/ExoplanetML/Nigraha/{COMMIT}/models/weights/global_nodropout/binary"
CHECKSUMS = {
    "models_1.hdf5": "aaa5ee66fa43b220cfc0e8a19a74bf12d98359c518a89c4a9421f7e096038266",
    "models_2.hdf5": "dbe07d4dc1ae53673cf71b4b4181aacf9770cf044bb6eaa2d2d30c91b6519da5",
    "models_3.hdf5": "28b0a3cd95bdb2481aa5c207239435d149d27072fda5a6e76063d69f1be86558",
    "models_4.hdf5": "a37fdb555158043f66d8a5f7a21a65a0ea6aea9f88720ec5d0d8ce73d373a1b4",
    "models_5.hdf5": "fe56a7579315b4631b7c207f564838bbc7bbaecf80f2c5288c204106d10cd501",
    "models_6.hdf5": "eaa2898dc96f181dccc7444d4a2c9bf7b1518822bbd56a9146ea53ffb6b76f26",
    "models_7.hdf5": "97624c5de8726439b3f076bba79a775a13daaec3685fbe7eb7b3badec6f969f1",
    "models_8.hdf5": "10ad3a38e97a1e50fcb861807459b42fcce2794503e4d138036f6ff22ac02ab7",
    "models_9.hdf5": "b352aa7e488936f25971dc61a1bedf298e8c3551d8857f339b1de62ed4125194",
    "models_10.hdf5": "76902567b4fad25208560e1b5cd6c19d55655d1265f5d86ad231c5c41694c80c",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, path: Path) -> None:
    with urlopen(url) as response, path.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch and register the published Nigraha TESS model weights.")
    parser.add_argument("--dest", type=Path, default=Path(".orbitlab/models/nigraha/global_nodropout/binary"))
    args = parser.parse_args()
    args.dest.mkdir(parents=True, exist_ok=True)

    for filename, expected in CHECKSUMS.items():
        target = args.dest / filename
        if not target.exists() or sha256_file(target) != expected:
            download(f"{BASE_URL}/{filename}", target)
        actual = sha256_file(target)
        if actual != expected:
            raise ValueError(f"checksum mismatch for {target}: expected {expected}, got {actual}")

    artifact = register_artifact(
        model_id="nigraha-tess-global-nodropout-binary-ensemble",
        mission="TESS",
        path=args.dest.resolve(),
        source=f"ExoplanetML/Nigraha models/weights/global_nodropout/binary at {COMMIT}",
        version=COMMIT,
    )
    print(f"registered={artifact.model_id}")
    print(f"path={artifact.path}")
    print(f"sha256={artifact.sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

