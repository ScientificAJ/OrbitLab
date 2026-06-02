from pathlib import Path

FORBIDDEN_SOURCE_SNIPPETS = [
    "mo" + "ck " + "planet",
    "dum" + "my " + "candidate",
    "place" + "holder " + "chart",
    "to" + "y " + "array",
]


def test_source_does_not_seed_fabricated_science_payloads():
    root = Path(__file__).resolve().parents[2]
    scanned = []
    for path in root.rglob("*"):
        if {"node_modules", ".venv", "__pycache__", "dist"} & set(path.parts):
            continue
        if not path.is_file():
            continue
        if path.name == "test_source_guards.py":
            continue
        if path.suffix not in {".py", ".ts", ".tsx", ".json", ".md"}:
            continue
        text = path.read_text(errors="ignore").lower()
        scanned.append(path)
        for snippet in FORBIDDEN_SOURCE_SNIPPETS:
            assert snippet not in text, f"{snippet!r} found in {path}"
    assert scanned
