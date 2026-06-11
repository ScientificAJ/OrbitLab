# Task: Scientific accuracy completion audit

- Start: 2026-06-10
- Cadence: task 3 of 3
- Goal: audit the claimed completion of the recent science mission against its
  own plan and live artifacts, close reviewable unfinished work, and push only
  after the full cadence verification suite.
- Expected verification: focused regressions, deep/paper truth benchmarks,
  unmocked live verification on named planets, full preflight, and final diff
  audit.

## Initial audit findings

- Round-3 live verification still falsely rejects known planet WASP-126 b.
- Both live TESS targets still report `triceratops_required`; the TRILEGAL
  resilience change did not achieve its intended live result.
- The execution log still describes completed benchmark/live work as
  running/next.
- The methodology contains an older contradictory selected-aperture claim.
- The untracked OrbitLab scientist skill promises three bundled resources that
  do not exist.

## Work completed in this audit pass (second agent)

- Per-event odd/even depths with median-event uncertainty in
  `validation.py`; cadence-pooled sigma kept only as a large-effect (>=20% of
  depth) EB guard via `odd_even_large_effect_fraction`. Fixed the pooled-stat
  overconfidence that falsely rejected WASP-126 b in round 3.
- Depth-supported transit counting (`_supported_transit_count`,
  `transit_support_depth_fraction = 0.5`); raw coverage kept as
  `covered_transit_count`.
- TRICERATOPS: `calc_probs` retries the alternate Monte Carlo path on
  IndexError, non-finite FPP/NFPP raises loudly, pipeline runs parallel=True.
- Live re-run at 23:39 (`completion-audit-live-wasp126.json`): TRICERATOPS
  completed live for the first time in-pipeline (FPP=0.0704, NFPP=0.0278,
  trilegal live_query). Odd/even false fail gone.

## Continuation (2026-06-11, resumed agent)

- The 23:39 live run still left WASP-126 b `rejected_signal`: the paper gate
  treated FPP/NFPP above the *validation* ceilings (0.015/0.001) as
  evidence-against hard fails. Per Giacalone et al. 2021 those are validation
  thresholds; rejection criteria are FPP > 0.5 / NFPP > 0.1, and the zone in
  between is statistically inconclusive (review, not rejection).
- Fixed: three-zone TRICERATOPS gating with new config keys
  `paper_triceratops_fpp_reject = 0.5`, `paper_triceratops_nfpp_reject = 0.1`;
  gray zone raises soft warnings `triceratops_fpp_inconclusive` /
  `triceratops_nfpp_inconclusive` (added to SOFT_REVIEW_WARNING_CODES);
  partial payloads (one finite value) are `triceratops_required` missing
  evidence.
- Fixed two test breaks left by the audit pass: `ValidationMetrics` gained
  `odd_even_pooled_sigma` without a default mid-dataclass (moved to defaulted
  tail), and the pipeline-edge ledger fixture had no real dips for the new
  depth-supported transit count (injected the candidate signal, same
  treatment the audit gave `test_tce_vetting` fixtures).
- Nigraha test failures seen mid-audit were CWD artifacts: the weights live
  at repo-root `.orbitlab/models/`, so pytest must run from the repo root
  (as `scripts/preflight.sh` does).
- Docs/CHANGELOG updated for all of the above; regression test
  `test_triceratops_inconclusive_zone_is_review_not_rejection` pins the
  WASP-126 b live values.
