# Contributing

OrbitLab uses a branch-and-PR workflow. Keep the pace high, but keep the science and repo hygiene visible.

## Team

See [TEAM.md](TEAM.md) for the current OrbitLab team roster and GitHub usernames.

## Branch-and-PR Workflow

1. Create a feature branch for your changes (e.g., `feature/description` or `fix/description`).
2. Keep commits small and named for the user-visible change.
3. Run `scripts/preflight.sh` locally before pushing your branch.
4. Push your branch and open a Pull Request to `main`.
5. Coordinate risky changes in issues or chat before editing shared surfaces.
6. Do not commit downloaded model artifacts, MAST cache data, databases, logs, virtual environments, frontend build output, or local runtime state.

> **Note:** A relaxed repository ruleset is available in `.github/rulesets/main.json`. This ruleset allows Administrators to bypass branch protections and supports all merge methods (Squash, Merge, Rebase).

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
