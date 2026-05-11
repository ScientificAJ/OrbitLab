# Gemini CLI Workflow

This repository uses a **Branch-and-PR workflow**.

## Mandatory Procedure

For every change, follow these steps:

1. **Create a branch**: Use a descriptive name like `feature/abc` or `fix/xyz`.
2. **Implement changes**: Follow the existing standards.
3. **Validate**: Run `scripts/preflight.sh` and any relevant tests.
4. **Push and PR**: Push the branch and create a Pull Request to `main`.

## Repository Rules

- NEVER push directly to `main`.
- ALWAYS use a branch for even the smallest changes.
- Ensure `scripts/preflight.sh` passes before creating a PR.
