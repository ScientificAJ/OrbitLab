# Changelog

All notable OrbitLab changes are tracked here.

## Unreleased

### Added

- Expanded documentation for the Science Provenance Release Room, release trust boundaries, model checksum readiness, deployment provenance checks, and submission evidence review.

## v0.2.0 - 2026-06-03

### Added

- Beginner onboarding guidance with a guided tour, coach marks, inline helpers, and technical tooltips.
- Voyager Mode easter egg with generated mission artwork and a persistent visual overlay toggle.
- Repository polish assets and automation for stronger GitHub presentation.
- Science Provenance Release Room generator with model checksums, calibration checksums, benchmark deltas, SPDX SBOM output, release-room checksums, and zipped release assets.
- GitHub release workflow that builds, uploads, and attests the release-room archive and SBOM.

### Changed

- Organized beginner guidance UI into a focused component module.
- Expanded frontend verification around onboarding, settings, mobile layout, and Voyager Mode.
- Upgraded CI, CodeQL, Dependabot, CODEOWNERS, branch ruleset, and release documentation for stronger repository trust.

## v0.1.0-mvp - 2026-05-11

### Added

- FastAPI backend for target search, product listing, TPF preview, BLS preview, analysis jobs, sessions, reports, and model readiness.
- React/Vite frontend for the full OrbitLab workflow.
- Real-data-first MAST target pixel file handling for TESS, Kepler, and K2.
- BLS candidate detection with periodograms, folded curves, validation context, and physics estimates.
- Mission-aware ML artifact readiness for Nigraha/TESS, AstroNet-family Kepler/K1, and ExoMAC-KKT K2.
- Docker Compose support, model artifact fetch scripts, CI, CodeQL, issue templates, release notes, and deployment documentation.
