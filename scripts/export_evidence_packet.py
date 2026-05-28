#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ensure_repo_venv(root: Path) -> None:
    venv_python = root / ".venv" / "bin" / "python"
    if venv_python.exists() and Path(sys.prefix).resolve() != (root / ".venv").resolve():
        os.execv(str(venv_python), [str(venv_python), *sys.argv])


def main() -> int:
    parser = argparse.ArgumentParser(description="Export an OrbitLab analysis result as an evidence packet.")
    parser.add_argument("result_json", help="Path to an analysis result JSON payload.")
    parser.add_argument("output_dir", help="Directory where the evidence packet should be written.")
    args = parser.parse_args()

    root = _repo_root()
    _ensure_repo_venv(root)
    sys.path.insert(0, str(root / "backend"))
    from orbitlab.science.evidence_packet import write_evidence_packet

    payload = json.loads(Path(args.result_json).read_text(encoding="utf-8"))
    summary = write_evidence_packet(payload, args.output_dir)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
