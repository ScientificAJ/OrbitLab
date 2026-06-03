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
