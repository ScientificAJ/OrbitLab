# Security Policy

## Supported Versions

OrbitLab is currently in student hackathon/prototype status. Security fixes are handled on the latest `main` branch and latest public release tag, currently `v0.2.0`.

## Reporting a Vulnerability

Please do not open a public issue for sensitive security problems.

Report privately through GitHub's private vulnerability reporting if it is enabled for this repository. If it is not available, contact the repository owner directly and include:

- A concise description of the issue.
- Steps to reproduce or affected API/UI paths.
- Whether credentials, local artifacts, downloaded model files, or user data are involved.
- Any suggested mitigation.
- Release tag, release-room asset, or GitHub Actions run if the report concerns release provenance, SBOM, or artifact attestation.

## Scope

Security reports are especially useful for:

- Exposed secrets or tokens.
- Unsafe file handling around downloaded MAST/model artifacts.
- Dependency vulnerabilities with a reachable exploit path.
- API behavior that could leak local paths, reports, or cached artifacts.
- Release workflow behavior that could publish misleading SBOM, checksum, or attestation evidence.

OrbitLab does not intentionally collect production user data. Local demo caches under `.orbitlab/` should not be committed.
