# Release And Milestone Notes

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

## Science Provenance Release Room

Every public release should include a release-room packet so OrbitLab can be
audited like a scientific instrument rather than only a compiled web app.

Generate the packet locally before publishing:

```bash
python scripts/build_release_room.py --tag vX.Y.Z --clean
```

The packet includes:

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

The `Science Provenance Release Room` GitHub Actions workflow also runs when a
release is published. It builds the frontend, fetches the pinned release model
artifacts, regenerates the packet inside GitHub Actions, uploads the packet as
release assets, and creates GitHub artifact attestations for the release-room
archive and SBOM.

For a manual rerun against an existing release, use:

```bash
gh workflow run release-room.yml -f tag=vX.Y.Z
```

Trust boundary:

- The release room proves source commit, generated assets, model checksums,
  benchmark evidence, and dependency inventory.
- It does not turn BLS, ML, or vetting outputs into confirmed planets.
- Missing or mismatched model artifacts must be reported as unavailable or
  mismatched, never replaced with synthetic evidence.

## Issue Labels

Recommended labels:

- `frontend`
- `backend`
- `science`
- `ml`
- `artifact`
- `deployment`
- `documentation`
- `good first issue`
- `demo-blocker`

## Milestones

- `Hackathon submission`: demo stability, documentation, screenshots, video.
- `Hosted demo`: DNS/TLS, deployment runbook, health checks, rollback.
- `Science hardening`: centroid checks, false-positive validation, stellar context.
- `Contributor readiness`: PR workflow, issue triage, release notes.
