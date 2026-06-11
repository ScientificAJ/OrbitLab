# Changelog

All notable OrbitLab changes are tracked here.

## Unreleased

### Added

- Expanded documentation for the Science Provenance Release Room, release trust boundaries, model checksum readiness, deployment provenance checks, and submission evidence review.
- Hardened truth benchmark: promotion-aware scoring that fails loudly, false-positive trap zoo (eclipsing binaries, background-EB secondary, odd/even mismatch, single deep event, sinusoid), multi-seed scrambled plus pure-noise false-alarm controls, and physics golden-radius checks against real planet values (TRAPPIST-1 b, HAT-P-7 b analogs).
- Unmocked live verification script (`scripts/live_planet_verification.py`) that drives the real API by planet name and compares recovered ephemerides/radii against NASA Exoplanet Archive golden values.
- Regression suite `backend/tests/test_accuracy_mission_fixes.py` pinning every accuracy fix.

### Fixed

- Transit searches no longer delete deep transits: BLS sigma clipping is now asymmetric (+6 sigma flares clipped, dips preserved), so hot Jupiters and deep M-dwarf transits survive the search.
- Red-noise beta is estimated on out-of-transit residuals (Pont et al. 2006), removing the inverted penalty where deeper planets looked noisier.
- Odd/even depth vetting uses event-centered transit numbering (round, not floor), restoring the eclipsing-binary half-period discriminator that parity splitting had silently disabled; same fix for observed-transit counting and DAVE per-event depths.
- BLS adds a local fine-grid period refinement pass, sharpening phase-based vetting and ephemeris accuracy to ~0.01 percent.
- Engine-unavailable hard failures (TLS/DAVE/SWEET/Nigraha/TRICERATOPS `*_required`) now block promotion as reviewable `borderline_tce` instead of mislabeling signals `rejected_signal`; TRICERATOPS incompletes report honestly instead of claiming "FPP above threshold".
- Planet physics consumes the merged stellar context (job -> curated known target -> live TIC catalog) with provenance, fixing solar-default radius corruption (up to ~9x) for known and catalog-resolved hosts; locked physics is a review warning, not a candidacy veto.
- Detrending sensitivity's transit-masked variant computes the trend on masked flux and applies it to the original flux instead of erasing the transit it was testing.
- Odd/even hard fails require real in-transit sampling (>=6 points, >=2 events per parity); sparse 30-minute-cadence cases downgrade to review warnings instead of false rejections.
- TRICERATOPS recovers the TIC id from the product URI when targets are searched by name (e.g. "L 98-59").
- DAVE ModShift engine failures and timeouts (budget raised 15s -> 120s) degrade to missing evidence instead of crashing the whole analysis job.
- Soft review warnings (catalog contamination, low ML probability, red noise already priced into effective SNR) no longer veto strong promotions; detection-quality warnings still block.
- TRILEGAL resilience for TRICERATOPS: the broken server certificate chain is repaired client-side by AIA-chasing the published ZeroSSL intermediate into a certifi bundle (verification still anchors at a trusted root — never `verify=False`), successful TRILEGAL tables are cached per TIC and replayed via `trilegal_fname`, and the payload reports `trilegal_source`.
- Nigraha cadence-domain guard: FFI-cadence (>300 s) TESS products mark ML scores `cadence_out_of_domain` — neutral in evidence scoring and missing-evidence (`nigraha_out_of_domain`) for paper-grade gates — instead of letting an out-of-domain score read as evidence against a planet.
- Product listings infer and expose `cadence_seconds` and rank short-cadence (2-minute) products first, so mission ML models run inside their training domain whenever the archive offers fast cadence.
- DAVE ModShift runs in a scratch directory; it no longer litters the repository root with `orbitlab-modshift-*` artifacts.
- Odd/even parity significance is computed from per-event depths (uncertainty of the median event depth), so long, densely sampled light curves can no longer become arbitrarily overconfident and falsely reject real planets with ordinary transit-to-transit variation; the cadence-pooled statistic survives only as a large-effect (>=20% of depth) eclipsing-binary guard.
- Transit counting now requires measured per-event depth support (>=50% of the detected depth), so coverage of an empty phase window no longer counts as an observed transit; raw coverage is reported separately as `covered_transit_count`.
- TRICERATOPS `calc_probs` retries the alternate Monte Carlo path on `IndexError` edge cases, rejects non-finite FPP/NFPP loudly, and runs parallel by default; live TESS runs now produce real FPP/NFPP through the repaired TRILEGAL chain.
- TRICERATOPS FPP/NFPP gating follows Giacalone et al. 2021 three-zone semantics: validated (no flags) below 0.015/0.001, likely false positive (evidence-against rejection) above 0.5/0.1, and a statistically inconclusive gray zone in between that blocks paper-grade validation as a soft review warning instead of falsely rejecting confirmed planets (this falsely rejected WASP-126 b live).

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
