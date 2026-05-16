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
4. Tag:

   ```bash
   git tag -a vX.Y.Z -m "OrbitLab vX.Y.Z"
   git push origin vX.Y.Z
   ```

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
