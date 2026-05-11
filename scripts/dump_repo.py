#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


INCLUDE_EXTENSIONS = {
    ".css",
    ".env",
    ".example",
    ".gitignore",
    ".html",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
}
INCLUDE_NAMES = {
    ".env.example",
    ".gitignore",
    "docker-compose.yml",
    "pyproject.toml",
    "README.md",
}
EXCLUDE_DIRS = {
    ".git",
    ".mypy_cache",
    ".orbitlab",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
    "orbitlab.egg-info",
}
EXCLUDE_NAMES = {
    "package-lock.json",
    "tsconfig.tsbuildinfo",
}


def should_include(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if not path.is_file():
        return False
    if any(part in EXCLUDE_DIRS for part in rel.parts):
        return False
    if path.name in EXCLUDE_NAMES:
        return False
    return path.name in INCLUDE_NAMES or path.suffix in INCLUDE_EXTENSIONS


def collect_files(root: Path) -> list[Path]:
    files = [path.relative_to(root) for path in root.rglob("*") if should_include(path, root)]
    return sorted(files, key=lambda path: path.as_posix())


def dump_repo(root: Path, output_path: Path) -> None:
    files = collect_files(root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write("# OrbitLab Repo Dump\n\n")
        handle.write(f"Generated from: {root}\n")
        handle.write(f"Files included: {len(files)}\n")
        handle.write("Excluded: .orbitlab, .venv, node_modules, dist, caches, package-lock.json\n\n")
        for rel in files:
            handle.write("\n" + "=" * 80 + "\n")
            handle.write(f"FILE: ./{rel.as_posix()}\n")
            handle.write("=" * 80 + "\n\n")
            handle.write((root / rel).read_text(encoding="utf-8", errors="replace"))
            handle.write("\n")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output_path = root / ".orbitlab" / "scratch" / "repodump.txt"
    dump_repo(root, output_path)
    print(output_path)
    print(f"{len(collect_files(root))} files")
    print(f"{output_path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
