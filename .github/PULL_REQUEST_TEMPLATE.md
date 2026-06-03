## Summary

-

## Area

- [ ] Frontend/UI
- [ ] Backend/API
- [ ] Science pipeline
- [ ] ML/model artifacts
- [ ] Documentation/repo hygiene
- [ ] Deployment/operations
- [ ] Release/provenance

## Validation

- [ ] `scripts/preflight.sh`
- [ ] Backend lint: `ruff check backend scripts`
- [ ] Backend tests
- [ ] Frontend format/lint/unit/e2e
- [ ] Frontend build
- [ ] GitHub Actions/CodeQL impact checked where relevant
- [ ] Documentation checked for real-data and model-provenance accuracy
- [ ] Release-room, SBOM, attestation, or GitHub metadata impact checked where relevant

## Science And Provenance

- [ ] Target IDs, product URIs, model IDs, source revisions, and checksums are preserved where relevant.
- [ ] Missing data or missing artifacts are reported as unavailable instead of replaced with synthetic outputs.
- [ ] Candidate language stays clear: BLS/ML outputs are support signals, not confirmed planets.
- [ ] Release-room evidence remains separate from target-level confirmation claims.

## Risk Review

- [ ] UI changes preserve existing layout contracts, theme persistence, and responsive behavior.
- [ ] API changes preserve payload semantics or document the migration clearly.
- [ ] Deployment-sensitive changes include rollback notes or a known-safe fallback.

## Notes

Direct push is the hackathon workflow, but this template keeps the repo contributor-ready for later PR review.
