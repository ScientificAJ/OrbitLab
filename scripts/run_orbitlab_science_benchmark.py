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
    parser = argparse.ArgumentParser(description="Run OrbitLab science truth-benchmark cases.")
    parser.add_argument("--mode", choices=("fast", "deep", "paper"), default="fast")
    parser.add_argument("--output-dir", default=".orbitlab/benchmarks/latest")
    args = parser.parse_args()

    root = _repo_root()
    _ensure_repo_venv(root)
    sys.path.insert(0, str(root / "backend"))
    from orbitlab.benchmarks import run_science_benchmark, write_benchmark_reports

    report = run_science_benchmark(vetting_mode=args.mode)
    paths = write_benchmark_reports(report, args.output_dir)
    print(json.dumps({"status": report["status"], "paths": paths}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
