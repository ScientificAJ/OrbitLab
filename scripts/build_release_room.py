#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ensure_repo_venv(root: Path) -> None:
    venv_python = root / ".venv" / "bin" / "python"
    if venv_python.exists() and Path(sys.prefix).resolve() != (root / ".venv").resolve():
        os.execv(str(venv_python), [str(venv_python), *sys.argv])


def _run(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=root, check=check, capture_output=True, text=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_dir():
        files = sorted(p for p in path.rglob("*") if p.is_file())
        if not files:
            raise ValueError(f"empty directory cannot be checksummed: {path}")
        for file_path in files:
            digest.update(str(file_path.relative_to(path)).encode("utf-8"))
            with file_path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
    else:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _git_metadata(root: Path) -> dict[str, Any]:
    status = _run(root, "git", "status", "--short").stdout.splitlines()
    return {
        "commit": _run(root, "git", "rev-parse", "HEAD").stdout.strip(),
        "branch": _run(root, "git", "branch", "--show-current").stdout.strip(),
        "describe": _run(root, "git", "describe", "--tags", "--always", "--dirty", check=False).stdout.strip(),
        "dirty": bool(status),
        "status_short": status,
    }


def _package_spdx_id(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9.-]+", "-", name).strip("-")
    return f"SPDXRef-Package-{safe or 'unknown'}"


def _python_dependency_packages(root: Path) -> list[dict[str, Any]]:
    pyproject = _load_json(root / "frontend" / "package-lock.json")
    # Keep the root package in the SBOM even though Python dependencies below come from pyproject.toml.
    root_package = pyproject.get("packages", {}).get("", {})
    packages = [
        {
            "SPDXID": "SPDXRef-Package-orbitlab",
            "name": "orbitlab",
            "versionInfo": _read_project_version(root),
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "NOASSERTION",
            "supplier": "Organization: OrbitLab",
            "externalRefs": [],
            "comment": "Python project metadata from pyproject.toml.",
        },
        {
            "SPDXID": "SPDXRef-Package-orbitlab-frontend",
            "name": root_package.get("name", "orbitlab-frontend"),
            "versionInfo": root_package.get("version", "NOASSERTION"),
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "NOASSERTION",
            "supplier": "Organization: OrbitLab",
            "externalRefs": [],
            "comment": "Frontend root package metadata from frontend/package-lock.json.",
        },
    ]
    return packages


def _read_project_version(root: Path) -> str:
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, flags=re.MULTILINE)
    return match.group(1) if match else "NOASSERTION"


def _npm_packages(root: Path) -> list[dict[str, Any]]:
    lock = _load_json(root / "frontend" / "package-lock.json")
    packages: list[dict[str, Any]] = []
    for package_path, package in sorted(lock.get("packages", {}).items()):
        if not package_path.startswith("node_modules/"):
            continue
        name = package_path.removeprefix("node_modules/")
        version = package.get("version", "NOASSERTION")
        resolved = package.get("resolved", "NOASSERTION")
        external_refs = []
        integrity = package.get("integrity")
        if integrity:
            external_refs.append(
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "npm",
                    "referenceLocator": f"pkg:npm/{name}@{version}",
                }
            )
        packages.append(
            {
                "SPDXID": _package_spdx_id(f"npm-{name}-{version}"),
                "name": name,
                "versionInfo": version,
                "downloadLocation": resolved,
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": str(package.get("license", "NOASSERTION")),
                "supplier": "NOASSERTION",
                "externalRefs": external_refs,
            }
        )
    return packages


def _pyproject_dependency_packages(root: Path) -> list[dict[str, Any]]:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    dependency_specs = list(pyproject.get("project", {}).get("dependencies", []))
    for group in pyproject.get("project", {}).get("optional-dependencies", {}).values():
        dependency_specs.extend(group)
    dependency_names = sorted({_dependency_name(spec) for spec in dependency_specs if _dependency_name(spec)})
    packages = []
    for name in dependency_names:
        packages.append(
            {
                "SPDXID": _package_spdx_id(f"pypi-{name}"),
                "name": name,
                "versionInfo": "NOASSERTION",
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "NOASSERTION",
                "supplier": "NOASSERTION",
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": f"pkg:pypi/{name}",
                    }
                ],
            }
        )
    return packages


def _dependency_name(spec: str) -> str:
    match = re.match(r"\s*([A-Za-z0-9_.-]+)", spec)
    return match.group(1).lower().replace("_", "-") if match else ""


def _build_sbom(root: Path, *, tag: str, generated_at: str, git_meta: dict[str, Any]) -> dict[str, Any]:
    packages = _python_dependency_packages(root)
    packages.extend(_pyproject_dependency_packages(root))
    packages.extend(_npm_packages(root))
    seen: set[str] = set()
    unique_packages = []
    for package in packages:
        if package["SPDXID"] in seen:
            continue
        seen.add(package["SPDXID"])
        unique_packages.append(package)
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"OrbitLab Science Provenance Release Room {tag}",
        "documentNamespace": (
            f"https://github.com/ScientificAJ/OrbitLab/releases/tag/{tag}"
            f"#spdx-{git_meta['commit'][:12]}"
        ),
        "creationInfo": {
            "created": generated_at,
            "creators": [
                "Tool: scripts/build_release_room.py",
                "Organization: OrbitLab",
            ],
        },
        "packages": unique_packages,
        "relationships": [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": "SPDXRef-Package-orbitlab",
            },
            {
                "spdxElementId": "SPDXRef-Package-orbitlab",
                "relationshipType": "CONTAINS",
                "relatedSpdxElement": "SPDXRef-Package-orbitlab-frontend",
            },
        ],
    }


def _artifact_checksums(root: Path) -> dict[str, Any]:
    registry_path = root / ".orbitlab" / "models.json"
    if not registry_path.exists():
        return {"registry_path": str(registry_path), "status": "unavailable", "artifacts": []}
    registry = _load_json(registry_path)
    artifacts = []
    for entry in registry.get("artifacts", []):
        artifact_path = Path(entry.get("path", ""))
        status = "ready"
        actual_sha256 = None
        detail = None
        if not artifact_path.exists():
            status = "unavailable"
            detail = f"path does not exist: {artifact_path}"
        else:
            try:
                actual_sha256 = _sha256_path(artifact_path)
                if actual_sha256.lower() != str(entry.get("sha256", "")).lower():
                    status = "checksum_mismatch"
                    detail = "actual checksum does not match registry checksum"
            except Exception as exc:
                status = "unavailable"
                detail = str(exc)
        artifacts.append(
            {
                **entry,
                "path_exists": artifact_path.exists(),
                "actual_sha256": actual_sha256,
                "status": status,
                "detail": detail,
            }
        )
    return {
        "registry_path": str(registry_path),
        "registry_sha256": _sha256_file(registry_path),
        "status": "ready",
        "artifacts": artifacts,
    }


def _calibration_checksums(root: Path) -> dict[str, Any]:
    candidates = [
        root / "backend" / "orbitlab" / "science" / "science_config.toml",
        root / "backend" / "orbitlab" / "science" / "science_config.py",
        root / "backend" / "orbitlab" / "ml" / "calibration.py",
        root / "docs" / "SCIENTIFIC_METHODOLOGY.md",
        root / "docs" / "MODEL_CARDS.md",
        root / "docs" / "model_artifacts.md",
        root / ".orbitlab" / "models" / "calibration",
    ]
    sources = []
    for path in candidates:
        if path.exists():
            sources.append(
                {
                    "path": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
                    "kind": "directory" if path.is_dir() else "file",
                    "sha256": _sha256_path(path),
                }
            )
        else:
            sources.append(
                {
                    "path": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
                    "kind": "missing",
                    "sha256": None,
                }
            )
    return {"status": "ready", "sources": sources}


def _run_benchmark(root: Path, output_dir: Path, mode: str) -> dict[str, Any]:
    benchmark_dir = output_dir / "benchmark"
    result = _run(
        root,
        sys.executable,
        "scripts/run_orbitlab_science_benchmark.py",
        "--mode",
        mode,
        "--output-dir",
        str(benchmark_dir),
    )
    return {
        "runner_stdout": result.stdout,
        "json_path": str(benchmark_dir / "benchmark_report.json"),
        "markdown_path": str(benchmark_dir / "benchmark_report.md"),
        "report": _load_json(benchmark_dir / "benchmark_report.json"),
    }


def _metric_delta(previous: dict[str, Any] | None, current: dict[str, Any], key: str) -> dict[str, Any]:
    current_value = current.get(key)
    previous_value = previous.get(key) if previous else None
    delta = None
    if isinstance(current_value, int | float) and isinstance(previous_value, int | float):
        delta = current_value - previous_value
    return {"previous": previous_value, "current": current_value, "delta": delta}


def _benchmark_delta(previous_path: Path | None, current: dict[str, Any]) -> dict[str, Any]:
    previous = _load_json(previous_path) if previous_path and previous_path.exists() else None
    metrics = {
        key: _metric_delta(previous, current, key)
        for key in (
            "known_planet_recovery_rate",
            "false_positive_rejection_rate",
            "injected_transit_recovery_rate",
            "case_count",
        )
    }
    return {
        "status": "baseline_unavailable" if previous is None else "ready",
        "baseline_path": str(previous_path) if previous_path else None,
        "metrics": metrics,
        "false_alarm_escape_list": {
            "previous": previous.get("false_alarm_escape_list") if previous else None,
            "current": current.get("false_alarm_escape_list"),
        },
        "missed_known_planets": {
            "previous": previous.get("missed_known_planets") if previous else None,
            "current": current.get("missed_known_planets"),
        },
        "unstable_candidates": {
            "previous": previous.get("unstable_candidates") if previous else None,
            "current": current.get("unstable_candidates"),
        },
    }


def _benchmark_delta_markdown(delta: dict[str, Any]) -> str:
    lines = [
        "# OrbitLab Science Benchmark Delta",
        "",
        f"- Status: `{delta['status']}`",
        f"- Baseline: `{delta.get('baseline_path')}`",
        "",
        "| Metric | Previous | Current | Delta |",
        "| --- | ---: | ---: | ---: |",
    ]
    for metric, values in delta["metrics"].items():
        lines.append(
            f"| {metric} | {values.get('previous')} | {values.get('current')} | {values.get('delta')} |"
        )
    lines.extend(
        [
            "",
            "## Escapes And Misses",
            "",
            f"- False alarm escapes: `{delta['false_alarm_escape_list']['current']}`",
            f"- Missed known planets: `{delta['missed_known_planets']['current']}`",
            f"- Unstable candidates: `{delta['unstable_candidates']['current']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _release_report_markdown(
    *,
    tag: str,
    generated_at: str,
    git_meta: dict[str, Any],
    model_checksums: dict[str, Any],
    calibration_checksums: dict[str, Any],
    benchmark: dict[str, Any],
    delta: dict[str, Any],
    sbom_package_count: int,
) -> str:
    benchmark_report = benchmark["report"]
    ready_models = [
        artifact["model_id"]
        for artifact in model_checksums.get("artifacts", [])
        if artifact.get("status") == "ready"
    ]
    unavailable_models = [
        artifact["model_id"]
        for artifact in model_checksums.get("artifacts", [])
        if artifact.get("status") != "ready"
    ]
    lines = [
        "# OrbitLab Science Provenance Release Room",
        "",
        f"- Release tag: `{tag}`",
        f"- Generated at: `{generated_at}`",
        f"- Commit: `{git_meta['commit']}`",
        f"- Branch: `{git_meta['branch']}`",
        f"- Working tree dirty at generation: `{git_meta['dirty']}`",
        "",
        "## Scientific Evidence",
        "",
        f"- Benchmark status: `{benchmark_report.get('status')}`",
        f"- Vetting mode: `{benchmark_report.get('vetting_mode')}`",
        f"- Case count: `{benchmark_report.get('case_count')}`",
        f"- Known planet recovery rate: `{benchmark_report.get('known_planet_recovery_rate')}`",
        f"- False positive rejection rate: `{benchmark_report.get('false_positive_rejection_rate')}`",
        f"- Injected transit recovery rate: `{benchmark_report.get('injected_transit_recovery_rate')}`",
        f"- Delta status: `{delta.get('status')}`",
        "",
        "## Model Provenance",
        "",
        f"- Registry status: `{model_checksums.get('status')}`",
        f"- Ready models: `{ready_models}`",
        f"- Unavailable or mismatched models: `{unavailable_models}`",
        "",
        "## Calibration Provenance",
        "",
        f"- Calibration/source files tracked: `{len(calibration_checksums.get('sources', []))}`",
        "",
        "## Supply Chain",
        "",
        "- SBOM format: `SPDX-2.3`",
        f"- SBOM package entries: `{sbom_package_count}`",
        "- GitHub Actions release workflow attests the release-room zip and SBOM when run from a release/tag.",
        "",
        "## Trust Boundary",
        "",
        "- This packet proves release inputs, build/test evidence, and artifact checksums.",
        "- It does not convert candidate detections into confirmed planets.",
        "- Missing model artifacts are reported as unavailable rather than silently replaced.",
    ]
    return "\n".join(lines) + "\n"


def _write_checksums(output_dir: Path) -> None:
    entries = []
    for path in sorted(output_dir.rglob("*")):
        if path.is_file() and path.name != "release-room-assets.sha256":
            entries.append(f"{_sha256_file(path)}  {path.relative_to(output_dir)}")
    (output_dir / "release-room-assets.sha256").write_text("\n".join(entries) + "\n", encoding="utf-8")


def _zip_release_room(output_dir: Path, tag: str) -> Path:
    archive_path = output_dir / f"orbitlab-release-room-{tag}.zip"
    if archive_path.exists():
        archive_path.unlink()
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output_dir.rglob("*")):
            if path.is_file() and path != archive_path:
                archive.write(path, path.relative_to(output_dir))
    return archive_path


def build_release_room(args: argparse.Namespace) -> dict[str, Any]:
    root = _repo_root()
    _ensure_repo_venv(root)
    sys.path.insert(0, str(root / "backend"))

    tag = args.tag
    output_dir = Path(args.output_dir or root / ".orbitlab" / "releases" / tag).resolve()
    if args.clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    generated_at = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    git_meta = _git_metadata(root)
    model_checksums = _artifact_checksums(root)
    calibration_checksums = _calibration_checksums(root)
    benchmark = _run_benchmark(root, output_dir, args.benchmark_mode)
    current_report = benchmark["report"]
    previous_path = (
        Path(args.previous_benchmark)
        if args.previous_benchmark
        else root / ".orbitlab" / "benchmarks" / "latest" / "benchmark_report.json"
    )
    if previous_path.resolve() == Path(benchmark["json_path"]).resolve():
        previous_path = None
    delta = _benchmark_delta(previous_path, current_report)
    sbom = _build_sbom(root, tag=tag, generated_at=generated_at, git_meta=git_meta)

    _write_json(output_dir / "release-metadata.json", {"tag": tag, "generated_at": generated_at, "git": git_meta})
    _write_json(output_dir / "model-artifact-checksums.json", model_checksums)
    _write_json(output_dir / "calibration-source-checksums.json", calibration_checksums)
    _write_json(output_dir / "science-benchmark-current.json", current_report)
    (output_dir / "science-benchmark-current.md").write_text(
        Path(benchmark["markdown_path"]).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _write_json(output_dir / "science-benchmark-delta.json", delta)
    (output_dir / "science-benchmark-delta.md").write_text(_benchmark_delta_markdown(delta), encoding="utf-8")
    _write_json(output_dir / "sbom.spdx.json", sbom)
    (output_dir / "orbitlab-release-report.md").write_text(
        _release_report_markdown(
            tag=tag,
            generated_at=generated_at,
            git_meta=git_meta,
            model_checksums=model_checksums,
            calibration_checksums=calibration_checksums,
            benchmark=benchmark,
            delta=delta,
            sbom_package_count=len(sbom["packages"]),
        ),
        encoding="utf-8",
    )

    _write_checksums(output_dir)
    archive_path = _zip_release_room(output_dir, tag)
    _write_checksums(output_dir)
    return {
        "status": "ready",
        "tag": tag,
        "output_dir": str(output_dir),
        "archive": str(archive_path),
        "archive_sha256": _sha256_file(archive_path),
        "asset_count": len([path for path in output_dir.rglob("*") if path.is_file()]),
        "benchmark_status": current_report.get("status"),
        "delta_status": delta.get("status"),
        "sbom_package_count": len(sbom["packages"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the OrbitLab Science Provenance Release Room asset set.")
    parser.add_argument("--tag", required=True, help="Release tag, for example v0.2.0.")
    parser.add_argument("--output-dir", help="Output directory. Defaults to .orbitlab/releases/<tag>.")
    parser.add_argument("--benchmark-mode", choices=("fast", "deep", "paper"), default="fast")
    parser.add_argument("--previous-benchmark", help="Previous benchmark_report.json for delta comparison.")
    parser.add_argument("--clean", action="store_true", help="Remove the output directory before generating assets.")
    summary = build_release_room(parser.parse_args())
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
