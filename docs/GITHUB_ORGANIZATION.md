# GitHub Repository Organization

Status: current for OrbitLab `v0.2.0`.

This guide keeps GitHub issues, labels, milestones, pull requests, and release evidence organized around OrbitLab's real work: science accuracy, product polish, deployment reliability, and release provenance.

## Repo Settings

Expected public settings:

- Default branch: `main`.
- Issues: enabled.
- Projects: enabled.
- Wiki: disabled, because source-controlled docs live in `docs/`.
- Delete branch on merge: enabled.
- License: MIT.
- Topics: astronomy, exoplanets, NASA/MAST, TESS, Kepler, FastAPI, React, machine learning, and provenance-oriented terms.

## Issue Templates

Use the issue forms by evidence type:

| Template               | Use for                                                                                          | Required evidence                                                                           |
| ---------------------- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------- |
| Bug report             | Reproducible app, API, workflow, or automation bugs.                                             | Steps, expected/actual behavior, environment, target/product details when relevant.         |
| Feature request        | Product, UI, science, API, deployment, documentation, or contributor improvements.               | Problem, proposal, affected area, constraints.                                              |
| Model artifact         | Model source, checksum, registry, runtime, or readiness problems.                                | Model ID, mission, source revision, checksum evidence, input contract.                      |
| Science result concern | Suspicious target result, TCE/candidate disposition, benchmark drift, or result wording problem. | Target/product IDs, candidate/TCE evidence, expected science behavior, trust-boundary area. |
| Release provenance     | Release-room asset, checksum, SBOM, attestation, or workflow problem.                            | Release tag, asset area, workflow/asset/checksum evidence.                                  |

Blank issues stay disabled so public issues keep enough provenance to reproduce the report.

## Labels

Labels should answer three questions quickly:

1. What area owns the issue?
2. What kind of work is it?
3. How risky or release-relevant is it?

Recommended label groups:

| Group            | Labels                                                                                                                 |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Area             | `frontend`, `backend`, `science`, `ml`, `artifact`, `deployment`, `documentation`, `security`, `release`, `provenance` |
| Work type        | `bug`, `enhancement`, `question`, `testing`, `ci`, `dependencies`, `github_actions`                                    |
| Contributor flow | `good first issue`, `help wanted`, `duplicate`, `invalid`, `wontfix`                                                   |
| Review focus     | `validation`, `repository`                                                                                             |

Rules:

- Use `science` for result semantics, TCE promotion, benchmark behavior, target/product evidence, or false-positive handling.
- Use `provenance` for checksums, release-room assets, model source traceability, SBOM, and attestations.
- Use `release` only when public release artifacts, tags, release notes, or release workflows are involved.
- Use `artifact` for model/data files and registries; combine it with `ml` for ML model bundles.
- Use `validation` for tests, benchmarks, evidence gates, and questionable candidate dispositions.

## Milestones

Milestones group work by outcome, not by file path:

| Milestone               | Purpose                                                                                  |
| ----------------------- | ---------------------------------------------------------------------------------------- |
| `v0.2.x stabilization`  | Fix regressions and polish public `v0.2.0` release evidence.                             |
| `Science hardening`     | Improve result accuracy, benchmark coverage, vetting gates, and false-positive handling. |
| `Hosted demo`           | Prepare deployment, DNS/TLS, model storage, health checks, and demo reliability.         |
| `Contributor readiness` | Improve PR workflow, docs, issue triage, templates, and onboarding.                      |

## Pull Request Routing

Use `.github/PULL_REQUEST_TEMPLATE.md` for every PR. Keep the science/provenance checklist honest:

- Preserve target IDs, product URIs, model IDs, source revisions, and checksums where relevant.
- Do not present BLS/ML outputs as confirmed planets.
- Document missing artifacts as unavailable, not as placeholder scores.
- For release-facing changes, check `docs/RELEASE.md` and the release-room workflow.

## Dependabot Triage

Dependabot PRs should keep their dependency labels and be triaged by stack:

- `frontend-runtime`, `frontend-tooling`, and `frontend-libraries` PRs need frontend format/lint/unit/e2e/build.
- `backend-runtime`, `science-stack`, and `ml-stack` PRs need backend tests and any targeted science/model checks.
- Major updates are intentionally ignored by Dependabot config and should be opened manually with a migration plan.

## Release Evidence Review

For each public release:

1. Confirm `docs/RELEASE.md` matches the release workflow.
2. Confirm the GitHub release contains release-room assets.
3. Verify the release-room zip attestation.
4. Check `model-artifact-checksums.json` for unexpected mismatches.
5. Check benchmark deltas for unexplained regressions.
6. Keep release-room evidence separate from target-level planet confirmation claims.
