# OrbitLab Demo Targets

These targets are practical starting points for local demos and smoke checks. Real MAST availability and product IDs can change, so treat this as a reproducible checklist rather than a scientific claim.

## TESS: TIC 307210830

- Search query: `TIC 307210830`
- Mission: `TESS`
- Expected flow: search result, TPF products, aperture preview, BLS preview, analysis job.
- Runtime notes: first product download can be slow because Lightkurve/MAST may fetch FITS files.
- Model notes: TESS ML readiness depends on Nigraha weights being fetched and checksum-valid.
- Demo caveat: BLS candidates are decision support, not confirmed planets.

## Kepler: Kepler-10

- Search query: `Kepler-10`
- Mission: `Kepler`
- Expected flow: search result and Kepler/K1 TPF products, then BLS preview/analysis if the product is available locally or MAST is reachable.
- Runtime notes: Kepler analysis may involve the TensorFlow runtime path when ML artifacts are present.
- Model notes: AstroNet readiness depends on the registered checkpoint and checksum validation.
- Demo caveat: missing model artifacts should be shown as unavailable, not hidden.

## TESS: TOI-700

- Search query: `TOI-700`
- Mission: `TESS`
- Expected flow: useful for demonstrating recognizable target search and model-readiness transparency.
- Runtime notes: product lists may include multiple sectors; choose one product and keep its ID visible in screenshots.
- Model notes: BLS preview should remain useful even when ML artifacts are unavailable.
- Demo caveat: known-object familiarity does not mean OrbitLab is confirming discovery.

## K2: EPIC 201367065

- Search query: `EPIC 201367065`
- Mission: `K2`
- Expected flow: K2 search/product exploration and model registry caveats.
- Runtime notes: K2 product availability can be more variable than TESS demo targets.
- Model notes: ExoMAC-KKT is the registered K2 replacement model and should be the K2 readiness surface.
- Demo caveat: use this target primarily to show honest unavailable states and mission-specific handling.

## Recommended Demo Script

1. Start `scripts/start_all.sh`.
2. Open the frontend URL printed by the script.
3. Search `TIC 307210830` with mission `TESS`.
4. Select a visible target pixel product and keep the product ID in view.
5. Open Aperture, select a few bright pixels, and apply the mask.
6. Run BLS Search and inspect candidate cards, periodogram, folded curve, and light curve.
7. Run Analysis and wait for validation/physics/ML context.
8. Open ML Status to show ready/unavailable model artifact truth.
9. Save a session, reopen Sessions, and restore it.
10. Export a report only after a full analysis result exists.
