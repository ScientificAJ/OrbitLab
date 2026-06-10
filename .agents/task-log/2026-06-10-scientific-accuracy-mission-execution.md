# Task: Scientific accuracy mission — execution

- Start: 2026-06-10 (follows the same-day inspection/plan task)
- Cadence: task 1 of 3 (new cadence; this task itself runs the full suite via
  preflight, benchmark all-modes, and live smoke because it is high
  blast-radius science-semantics work)
- Goal: drive measured scientific accuracy to near-100% with an honest truth
  benchmark; fix every factor it exposes; verify unmocked on real planet
  names before push.

## Science bugs found and fixed (each pinned by a regression test in
## backend/tests/test_accuracy_mission_fixes.py)

1. `bls.py sigma_clip_flux`: symmetric ±6σ clip deleted every transit deeper
   than 6× noise (hot Jupiters on quiet stars = 30σ+). Now asymmetric:
   +6σ / −50σ.
2. `evidence.py` red-noise beta included the transit itself → deeper planet =
   higher beta = lower effective SNR + red_noise warning. Now estimated on
   out-of-transit residuals (Pont et al. 2006).
3. `validation.py` odd/even parity used floor() with an epoch-centered window
   → every event's points split across two transit numbers → odd/even
   discriminator collapsed (EBs passed). Now round(). Same fix in
   `pipeline._observed_transit_count` (overcounted transits) and
   `dave_vetting._transit_depth_series`.
4. `bls.py run_bls`: broad geometric grid leaves ~0.1% period error which
   smears phase-based vetting; added ±1.5% linear fine refinement (2001
   samples). EB odd/even now sharp.
5. `pipeline._disposition`: engine-unavailable hard fails (triceratops/
   nigraha/TLS/DAVE/SWEET *_required) now block promotion as borderline_tce
   instead of branding the signal rejected_signal (GOAL.md §9). TRICERATOPS
   incomplete now flags `triceratops_required` with an honest message instead
   of lying "FPP above threshold".
6. Physics used job-only stellar params, ignoring merged known-target/TIC
   context → solar-default radii (3-10x wrong) + interpretation_locked +
   promotion demotion for every target without explicit job stellar input.
   Now consumes the merged context with provenance; locked physics is a
   review warning, not a candidacy veto.
7. Soft-warning policy: catalog_contamination/nigraha_low_probability/
   red_noise etc. no longer veto strong promotions (red_noise beta already
   deflates effective SNR — double penalty removed). low_snr/harmonic still
   block. Hardcoded 7.1 in validation low_snr now parameterized from config.
8. `detrending_sensitivity.py` transit-masked variant erased the transit then
   searched for it → every strong candidate marked unstable_result →
   detrending_unstable blocker. Now computes trend on masked flux, applies to
   original flux.

## Benchmark (Phase 1/4)

- 13 cases: 4 planet-truth (incl. TRAPPIST-1b analog via known-target M-dwarf
  context, HAT-P-7b analog on Kepler path) with promotion-required scoring +
  physics golden radius checks; 5 FP traps (EB, background EB secondary,
  odd/even mismatch, single deep event, sinusoid); 3 scrambled + 1 pure-noise
  false-alarm controls. Status fails loudly on any miss/escape/physics fail.
- Fast mode: 13/13. Before fixes: planet promotion 0%, EB escaped after
  un-clipping. After: recovery 1.0, rejection 1.0, promoted recovery 1.0,
  physics failures none, escapes none. Reports in
  `.orbitlab/benchmarks/accuracy-mission-after*`.

## Verification so far

- backend pytest full suite: 369 passed (after updating 3 tests asserting the
  old conflated semantics + 1 fixture missing fpp status).
- New regression file: 8 tests passing.
- ruff: clean. Frontend greps show no hard-coded changed flag codes.
- docs/SCIENTIFIC_METHODOLOGY.md updated (clip, beta, odd/even, disposition
  classes, refinement, stellar provenance).
- Deep-mode benchmark running in background; preflight + unmocked live run on
  real planet names (L 98-59 / TIC 307210830 cached TPF, Kepler-10) next.

## Live unmocked verification (Phase 6, real planet names, paper mode)

Round 1 exposed three more real-data bugs (fixed + regression-tested):
- odd/even hard-failed L 98-59 c on 1-2 points/event (30-min FFI) while DAVE
  ModShift's own odd/even metric passed → sparse-sampling guard added.
- TRICERATOPS demanded a numeric TIC and broke for name searches ("L 98-59")
  → TIC parsed from product URI as fallback.
- ModShift 15s timeout crashed the whole Kepler-10 job → 120s budget +
  failure degrades to missing evidence.

Round 2 results (vs NASA Exoplanet Archive):
- L 98-59 c: P 3.68956 vs 3.69068 (0.03%), Rp 1.36 vs 1.385 R⊕ (1.8%),
  disposition borderline_tce/review_needed (only hard fail:
  triceratops_required — TRILEGAL server SSL cert broken, external).
- WASP-126 b: P 3.29101 vs 3.2888 (0.07%), Rp 10.92 vs 10.8 R⊕ (1.1%),
  borderline_tce same reason; ModShift pass; SDE 30.6.
- Junk sub-day residual TCEs on both targets correctly rejected_signal with
  implausible_duration (evidence-against).
- Stellar context resolved live from TIC catalog (physics_source=tic_catalog).
- Kepler-10: result recorded in
  `.orbitlab/benchmarks/live-planet-verification-round2/kepler-10/`.

## Remaining known gaps (honest)

- PRF-fit centroiding still image-moment based (uncertainty propagated).
- Per-population TLS SDE recalibration not runtime-implemented.
- Sinusoidal variability case intentionally stays a reviewable borderline TCE
  (near-escape list), not auto-rejected.
