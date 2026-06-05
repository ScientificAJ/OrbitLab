# Operation Friday Beta Manual Visual Review

Date: 2026-06-03

This review corrects an earlier audit gap. The first Operation Friday Beta pass
checked endpoint health, JSON payload shape, candidate-array consistency,
periodogram/folded-curve presence, and automated ledger semantics. That was not
enough. The visual products had to be rendered and inspected directly.

## Scope

Visual boards were generated from the saved API workflow payloads using
`operation-friday-beta/render_visual_audit.py`. Each board includes:

- TPF preview with selected aperture overlay.
- Periodogram with candidate-period markers.
- Folded curves for up to four candidates.
- Candidate period, SNR, depth, disposition, readiness, and depth provenance.

The automated audit status `pass` means the API workflow and science payload
contracts were internally consistent. It does not mean the plotted signal is a
confirmed planet.

## Important Finding Fixed

Manual graph inspection exposed a real science/reporting bug: TLS model depths
were being reported as candidate depths even when the visual folded curves
showed much smaller flux dips. Some primary TLS candidates were effectively
reporting near-unity model depth values, which was scientifically misleading.

The fix now measures depth from the folded transit phase window on the actual
flux array and records provenance:

- `depth_fraction` / `depth_ppm`: measured phase-window depth when available.
- `model_depth_fraction`: raw BLS/TLS model depth retained for traceability.
- `measured_depth_fraction`: measured value used for reporting.
- `depth_source`: `phase_window_median` when measured depth is used.

After the fix, the displayed candidate depths are compatible with the plotted
flux scale.

## Case Review

### tess_known_hot_jupiter

- TPF/aperture: aperture is centered on the bright TESS source and includes a
  reasonable surrounding selection.
- Periodogram: several marked periods appear, with broad noisy structure.
- Folded curves: no clean, symmetric hot-Jupiter transit is visually recovered
  in this selected product. The highest-SNR folds contain scattered points and
  narrow dips that do not justify promotion.
- Conclusion: API consistency passes; scientific conclusion remains cautious.
  The rejected/blocked candidate state is appropriate.

### tess_multi_known

- TPF/aperture: aperture is centered on the target-like flux concentration.
- Periodogram: candidate power is present, but the search is noisy.
- Folded curves: the folds do not show clear repeated multi-planet transit
  morphology. The primary signal is low SNR after measured-depth correction.
- Conclusion: API consistency passes; visual evidence does not support a clean
  automated planet claim in this run. Rejection/blocking is appropriate.

### kepler_multi_known

- TPF/aperture: aperture is centered and visually plausible for the Kepler
  target pixel product.
- Periodogram: a strong periodogram peak aligns with the primary candidate.
- Folded curves: the primary fold shows the clearest transit-like dip at phase
  zero among the five cases. The measured depth is now around the plotted flux
  scale and matches the visual dip order of magnitude.
- Conclusion: this is the strongest visual recovery. It is still blocked as
  `review_needed` because paper-grade readiness gates are not fully satisfied,
  so the UI/API must present it as a known-system-aligned candidate requiring
  review, not as a confirmed planet.

### k2_multi_known

- TPF/aperture: aperture surrounds the main source with nearby field structure
  visible.
- Periodogram: broad/noisy structure with candidates at short and around
  ten-day periods.
- Folded curves: the primary fold has some phase-zero depression but also
  scattered outliers and no clean planet-quality profile. The secondary signal
  is not convincing.
- Conclusion: API consistency passes; visual confidence is not high enough for
  promotion. Borderline/blocking remains the safer scientific state.

### tess_control_candidate

- TPF/aperture: aperture is centered on a real TESS source.
- Periodogram: candidate periods are detected.
- Folded curves: the primary fold shows a narrow phase-zero streak/outlier
  structure rather than a clean transit shape. SNR alone is misleading here.
- Conclusion: this is exactly why visual review matters. The automated
  rejection is correct; it should not be treated as a planet-like result.

## Final Interpretation

Operation Friday Beta now has two separate trust levels:

1. API workflow pass: all five real-data workflows completed and produced
   internally consistent payloads.
2. Visual/scientific review: only Kepler-10 shows a strong transit-like visual
   recovery, and even that remains blocked pending paper-grade readiness. The
   other four cases are correctly rejected or blocked based on the current
   evidence.

The product should keep exposing provenance, readiness, and rejection reasons
instead of flattening these cases into a single success label.

## Operational Risk

K2 paper-mode analysis is slow on the current workflow because the TLS/model
checks run over a large cadence and period grid. The final rerun completed, but
K2 was the clear runtime bottleneck. That is not a correctness failure, but it
is a product/reliability risk for user-facing wait time and should be optimized
with cached intermediate evidence, narrower known-target windows, or an
explicit long-running analysis UX if this path remains part of the main flow.

## 2026-06-04 Live Re-run + Manual Science Cross-Check

The full API sweep was re-run live against real MAST so the API freshly
generated every product (search, products, TPF preview, aperture mask, BLS
preview, analysis, periodogram, folded curves, candidate ledger, report,
session). Each product was then manually cross-checked against published
literature values. New findings:

### Finding 1 (fixed): Kepler AstroNet ML never executed
The `/models` endpoint advertised `kepler_astronet: ready`, but every Kepler ML
inference failed and silently fell back to `ml-unavailable`. Root cause: the
Docker runtime pins `tensorflow/tensorflow:1.5.0-py3` (Python 3.5.2), while
`scripts/predict_kepler_astronet_tf.py` used f-strings (Python 3.6+). The
helper raised `SyntaxError` on first parse inside the container even though it
was valid on the host. Fix: the three f-strings were rewritten with
`str.format()`. Verified the script now parses under Python 3.5.2 inside the
pinned image, and a live Kepler re-run produced real, distinct AstroNet
probabilities (no more `ml-unavailable`). Net effect: AstroNet had never scored
anything on this pinned image until this fix.

### Finding 2 (open): Nigraha TESS probability pinned at 0.3
Nigraha returned `raw_ml_probability == 0.3` for every TESS candidate across all
TESS cases (8 distinct input-tensor checksums, identical output). The service
has no 0.3 default, so the ensemble itself is collapsing to a fixed point —
most likely because the stellar features (Teff/Radius/logg/Mass/lum/rho) are
fully imputed when catalog context is missing. Conservative impact only (all
affected candidates were rejected, threshold 0.4), but the TESS ML surface is
not providing real discrimination in this run. Needs an isolated investigation
before any model-code change.

### Finding 3 (minor): top-level depth provenance fields null
`depth_source` / `model_depth_fraction` / `measured_depth_fraction` are null at
the top level of each candidate but populated inside `detection_metrics`. The
audit checks both, but a UI reading the top-level field would see null
provenance.

### Method limitation: TOI-700 planets unrecoverable as configured
TOI-700's known planets are at ~9.98, ~16.05, ~27.8 and ~37.4 days. The sweep
used a single-sector SPOC TPF with `max_period=30`, so planet d (37.4 d) is
outside the search window and the others need multi-sector SNR. The rejection
is correct for this product, but the operation cannot recover TOI-700's real
planets with these settings.

### Literature cross-check (this run)
- Kepler-10 b: published P=0.8375 d, depth ~152 ppm, dur ~1.8 h. OrbitLab:
  P=0.83599 d, depth 159 ppm, dur 1.91 h. Accurate recovery; correctly held as
  `borderline_tce / blocked` with catalog match "Kepler-10 b". Post-fix AstroNet
  scores it low and self-flags `domain_awareness: inconclusive`
  (`fallback_stellar_context`); the system correctly does not let the OOD ML
  score override the strong BLS/physics + catalog evidence.
- EPIC 201367065 (K2-3): published K2-3 b P~10.05 d, depth ~1100 ppm. OrbitLab:
  P=10.055 d, depth 1265 ppm, SNR 32.7 — the strongest recovery in the
  operation. ExoMAC-KKT ML ran normally (the K2 path is RandomForest, not the
  Kepler TF path). Correctly held, not over-promoted.
- TIC 25155310 (control): TCE-1 has SNR 125.8 and a 6400 ppm dip but is
  correctly rejected as `not-transit-like`. This is the key control success: a
  naive SNR cut would falsely promote a deceptive non-transit signal; OrbitLab
  rejects it.

### Verdict
All five products are internally consistent and, where a known planet exists,
the recovered period/depth/duration match published values. No false planet
promotions occurred. The one real defect (Kepler AstroNet never running) is
fixed and verified live. Two issues remain open for follow-up (Nigraha pinned
probability; top-level depth provenance fields).

## 2026-06-05 Follow-up fixes (Nigraha root cause, depth provenance, period/baseline)

The three open follow-ups were investigated to root cause and fixed. All three
were re-verified live against real MAST by re-running the three TESS cases in
paper-grade mode (TIC 307210830, TOI-700, TIC 25155310) plus a direct
custom-period-bounds job. All cases audit `pass` with 0 findings.

### Finding 2 RE-DIAGNOSED + handled honestly: Nigraha 0.3 was NOT just missing context
The deeper investigation found the pinned probability is a **preprocessing
defect, not a context gap**. The released Nigraha CNN expects its scalar features
(Teff, R*, logg, mass, luminosity, density, depth, duration, Rp/Rs, odd/even
depths) to be standardized — subtract median, divide by std — before the dense
head (Rao et al. 2021, MNRAS 502, 2845, sec. 3;
https://academic.oup.com/mnras/article/502/2/2845/6121433). OrbitLab's numpy
reimplementation fed the **raw physical values** (e.g. Teff ≈ 5778) straight into
the dense layers, driving the final logit to ≈ -900 to -4000, so the sigmoid
saturates to a constant (~8.8e-27 → 0.3 after calibration) for essentially any
input. Our golden test fixture had captured this same un-normalized forward pass,
so the bug looked "validated."

We do NOT hold the upstream training-set median/std constants, and fabricating
our own normalization would produce scores not validated against the published
model. So, per the chosen NASA-rigorous path, we **did not invent normalization**.
Instead:
- The job→known_target→TIC stellar-context wiring was still landed (it is correct
  and improves provenance): real TIC Teff/R*/mass/logg/lum now flow into the ML
  surface, recorded as `ml.stellar_context_source` (verified live: all five
  stellar fields source from `tic_catalog`, lookup `complete`).
- The service now **detects the saturated regime** (ensemble |logit| ≥ 50) and
  flags it honestly: `ml.saturated=true`, `ml.score_confidence=degenerate_saturated`,
  `ml.preprocessing_compatible=false`, with a paper-cited `ml.score_caveat`. Because
  the existing evidence-fusion keys OOD off `preprocessing_compatible`, the score is
  automatically routed to `domain_awareness: inconclusive` and cannot override
  BLS/physics/catalog evidence. The pinned 0.3 is now exposed as degenerate, not
  trusted — which is the correct, conservative behavior.

### Finding 3 FIXED: top-level depth provenance fields
`depth_source` / `model_depth_fraction` / `measured_depth_fraction` were computed
into the candidate dict but dropped by Pydantic because `TcePayload` never declared
them. The schema now declares all three. Verified live: every TESS TCE now reports
`depth_source: phase_window_median` (or `astropy_box_least_squares`) and a non-null
`measured_depth_fraction` at the top level, matching the `detection_metrics` copy.

### Method limitation RESOLVED into an explicit diagnostic: TOI-700 baseline
The earlier "30-day window" note was wrong — paper-grade already searches to 60 d.
The real reason single-sector TESS cannot recover TOI-700 d (37.4 d) is the
~22–27 d baseline: ≥2 transits requires P ≤ baseline/2. This is now surfaced, not
hidden: every result carries `period_window` (request vs profile vs effective
window) and a `period_window_note` of status `baseline_limited` stating the max
recoverable period for the observed baseline (verified live: ~10.9–12.3 d for the
TESS cases) and that long-period recovery needs a multi-sector baseline. The
analysis request now also honors `min_period`/`max_period` (verified live: a job
with `min_period=2, max_period=8` produced an effective 2–8 d window,
`honored: true`). True multi-sector stitching remains a separate, deferred feature.

### Final verdict (post-fix)
All five products remain internally consistent with no false planet promotions.
Kepler-10 b and K2-3 b recoveries are unchanged and still correctly held. The
Nigraha defect is now understood (missing upstream scalar standardization) and
gated honestly rather than silently trusted; depth provenance is visible at the
contract top level; and the baseline limitation is an explicit, paper-grounded
diagnostic instead of a silent rejection.
