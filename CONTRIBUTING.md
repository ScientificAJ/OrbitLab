# Contributing

OrbitLab is in hackathon direct-push mode. Keep the pace high, but keep the science and repo hygiene visible.

## Direct-Push Workflow

1. Pull before starting work.
2. Keep commits small and named for the user-visible change.
3. Run `scripts/preflight.sh` before pushing.
4. Coordinate risky changes in issues or chat before editing shared surfaces.
5. Use a short branch for dangerous or speculative changes.
6. Do not commit downloaded model artifacts, MAST cache data, databases, logs, virtual environments, frontend build output, or local runtime state.

## Local Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,science,api,ml]"
npm ci --prefix frontend
```

## Preflight

```bash
scripts/preflight.sh
```

The preflight runs backend tests, frontend build, shell syntax checks for startup scripts, and Python compile checks for operational scripts.

## Science Standards

- Use real MAST products for demos and fixtures.
- Preserve target IDs, product URIs, model IDs, source revisions, and checksums.
- Never replace missing model artifacts with fake scores.
- Never present BLS candidates as confirmed exoplanets.
- Document limitations close to the feature that exposes them.
