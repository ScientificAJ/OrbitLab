# Task: Scientific accuracy mission — inspection + boost plan (no edits yet)

- Start: 2026-06-10
- Cadence: task 3 of 3 (prior: codecov-100-percent = task 2). This task is
  read-only inspection/planning; the deferred full-suite cadence run will be
  executed at the start of the upcoming execution phase (user will signal).
- Goal: Map why OrbitLab's real accuracy feels ~70%, define measured-accuracy
  denominators, and plan the path to near-100% (NASA-grade) for user approval.
- Expected verification: none this task (no code changes). Baseline fast
  benchmark re-run only, output in
  `.orbitlab/benchmarks/accuracy-mission-baseline/`.

## Key findings (evidence)

1. Benchmark harness (`backend/orbitlab/benchmarks/science_benchmark.py`)
   has only 5 synthetic cases and lenient scoring:
   - Planet cases score "recovered" without requiring promotion, even though
     `expected_disposition="planet_candidate"`. All planet cases land as
     `borderline_tce`, 0 promotions, yet all rates report 1.0.
   - FP "rejection" = "not promoted" — trivially satisfied because nothing is
     ever promoted in fast mode. The sinusoidal-variability trap produced a
     clean no-hard-fail TCE (`signal_recovered=True`) — a near-escape that the
     scoring ignores.
   - Eclipsing-binary case recovers an aliased period (>2% error), only
     listed as "unstable", not failed.
2. Real-data live audit (`operation-friday-beta/reports/`): TIC 307210830
   (= L 98-59, multi-planet M-dwarf) produced TCE-1 at 3.68956 d, matching
   real planet L 98-59 c (3.690 d), SNR 16.5 — and it was dispositioned
   `rejected_signal` with RoboVet "not-transit-like". A real known planet is
   being falsely rejected by vetting on real data. The audit still "passes"
   because it audits API consistency, not scientific truth.
3. `docs/SCIENTIFIC_METHODOLOGY.md` honestly lists deltas: no per-regime
   SDE/false-alarm calibration, box-only residual search, moment centroid,
   solar-default stellar params, fixed biweight detrending, approximate SWEET.
4. Skill bundle `.claude/skills/orbitlab-scientist` is missing
   `references/accuracy-playbook.md`, `references/api-probing.md`, and
   `scripts/api_probe.py` (only module-flow.md exists). Logged; fell back to
   repo artifacts.

## Plan (reported to user; awaiting signal)

Phase 1 truth-harness hardening → Phase 2 fix exposed factors (RoboVet false
rejection, promotion logic, alias handling) → Phase 3 physics upgrades
(limb-darkened residual search, full TRICERATOPS aperture path, centroid
motion baseline, stellar-param guards) → Phase 4 false-alarm/SDE calibration +
injection heatmap → Phase 5 full verification + live re-audit + delta report.
