# Release And Milestone Notes

Status: current for OrbitLab `v0.2.0` and the Science Provenance Release Room workflow.

OrbitLab releases are treated as scientific instrument releases, not only code snapshots. A good release must answer four questions:

1. Which source commit produced this release?
2. Which science/model/calibration inputs were available and checksum-valid?
3. What did the benchmark suite say at release time?
4. What dependency and release assets can reviewers audit later?

## Release Tagging

1. Confirm `scripts/preflight.sh` passes.
2. Confirm frontend checks:

   ```bash
   npm run lint --prefix frontend
   npm run format:check --prefix frontend
   npm run test:unit --prefix frontend
   npm run test:e2e --prefix frontend
   npm run build --prefix frontend
   ```

3. Update release notes with:
   - user-facing changes
   - science/ML limitations
   - model artifact requirements
   - known unavailable states
4. Update `CHANGELOG.md` and keep the release entry aligned with the GitHub release body.
5. Regenerate README demo assets if the UI changed:

   ```bash
   npm run capture:demo-assets --prefix frontend
   ```

6. Tag:

   ```bash
   git tag -a vX.Y.Z -m "OrbitLab vX.Y.Z"
   git push origin vX.Y.Z
   ```

7. Confirm the release-room workflow finishes and that GitHub release assets are present:

   ```bash
   gh run list --workflow release-room.yml --limit 5
   gh release view vX.Y.Z
   ```

## Science Provenance Release Room

Every public release should include a release-room packet so OrbitLab can be
audited like a scientific instrument rather than only a compiled web app.

Generate the packet locally before publishing:

```bash
python scripts/build_release_room.py --tag vX.Y.Z --clean
```

Use `--benchmark-mode fast`, `deep`, or `paper` to choose the benchmark gate for the packet. Public GitHub release automation currently uses `fast` so release asset generation remains practical in Actions. Local maintainers can run `deep` or `paper` before release when the machine has the full science runtime and model artifacts available:

```bash
python scripts/build_release_room.py --tag vX.Y.Z --benchmark-mode paper --clean
```

The packet writes to `.orbitlab/releases/<tag>/` by default and includes:

- `orbitlab-release-report.md`
- `release-metadata.json`
- `model-artifact-checksums.json`
- `calibration-source-checksums.json`
- `science-benchmark-current.json`
- `science-benchmark-current.md`
- `science-benchmark-delta.json`
- `science-benchmark-delta.md`
- `sbom.spdx.json`
- `release-room-assets.sha256`
- `orbitlab-release-room-vX.Y.Z.zip`

Asset meanings:

| Asset                               | What it proves                                                                                                             | What it does not prove                                                               |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `release-metadata.json`             | Git commit, branch, tag input, dirty-tree state at generation time.                                                        | That the released tag was the latest commit on `main`.                               |
| `model-artifact-checksums.json`     | Registered model paths, expected checksums, actual checksums, and readiness/mismatch states.                               | That a model score confirms a planet.                                                |
| `calibration-source-checksums.json` | Checksums for science config, calibration code, and key methodology/model docs used as calibration-facing source context.  | That every external astronomy assumption is perfect.                                 |
| `science-benchmark-current.*`       | Current benchmark metrics for known planets, injected signals, false positives, scrambled controls, and variability cases. | That every target outside the benchmark set will behave the same.                    |
| `science-benchmark-delta.*`         | Movement against the previous benchmark report when available.                                                             | That missing baseline data is harmless; a missing baseline must be reported.         |
| `sbom.spdx.json`                    | Python project, pyproject dependencies, frontend root package, and npm packages in SPDX 2.3 form.                          | That every dependency is vulnerability-free. Use CI/security scanning too.           |
| `release-room-assets.sha256`        | Checksums for all generated release-room files, including the zip after the second checksum pass.                          | That assets uploaded by a third party are unchanged unless the checksum is verified. |
| `orbitlab-release-room-vX.Y.Z.zip`  | Portable bundle of the complete packet.                                                                                    | That all live services are currently healthy.                                        |

The `Science Provenance Release Room` GitHub Actions workflow also runs when a
release is published. It builds the frontend, fetches the pinned release model
artifacts, regenerates the packet inside GitHub Actions, uploads the packet as
release assets, and creates GitHub artifact attestations for the release-room
archive and SBOM.

For a manual rerun against an existing release, use:

```bash
gh workflow run release-room.yml -f tag=vX.Y.Z
```

After the workflow succeeds, verify the release-room asset and attestation:

```bash
gh release download vX.Y.Z --pattern 'orbitlab-release-room-vX.Y.Z.zip'
gh attestation verify orbitlab-release-room-vX.Y.Z.zip --repo ScientificAJ/OrbitLab
```

If the workflow succeeds but assets are missing, rerun the workflow by tag. The workflow uses `gh release upload --clobber`, so a successful rerun should replace stale assets without requiring a new release tag.

Trust boundary:

- The release room proves source commit, generated assets, model checksums,
  benchmark evidence, and dependency inventory.
- It does not turn BLS, ML, or vetting outputs into confirmed planets.
- Missing or mismatched model artifacts must be reported as unavailable or
  mismatched, never replaced with synthetic evidence.

Release-room review checklist:

- `release-metadata.json` commit matches the intended release commit or the mismatch is explained in the release notes.
- `model-artifact-checksums.json` has no surprise `checksum_mismatch` entries.
- `science-benchmark-current.json` status is acceptable for the release goal.
- `science-benchmark-delta.json` shows no unexplained benchmark regression.
- `sbom.spdx.json` exists and the GitHub attestation verifies for the release-room zip.
- The GitHub release includes the generated Markdown/JSON/SBOM/checksum files and the zip.

## Issue Labels

Recommended labels:

- `frontend`
- `backend`
- `science`
- `validation`
- `ml`
- `artifact`
- `deployment`
- `documentation`
- `release`
- `provenance`
- `security`
- `testing`
- `ci`
- `repository`
- `good first issue`
- `demo-blocker`

## Milestones

- `v0.2.x stabilization`: release evidence, docs, repo hygiene, and regression polish for the public `v0.2.0` line.
- `Hosted demo`: DNS/TLS, deployment runbook, health checks, rollback.
- `Science hardening`: centroid checks, false-positive validation, stellar context.
- `Contributor readiness`: PR workflow, issue triage, release notes.
