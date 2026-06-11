# HANDOVER — Nigraha/SWEET fixes (mid-flight) + PRF centroiding + SDE calibration

- Date: 2026-06-11
- From: Fable 5 session (investigation + implementation half)
- To: testing/continuation agent (verification + completion + push half)
- Repo state when written: branch `main`, last pushed commit `753b472`
  ("science: per-event odd/even stats and Giacalone three-zone FPP gating").
  Everything below describes UNCOMMITTED working-tree changes plus unstarted
  work. `git status` should show exactly these modified files:
  - `backend/orbitlab/science/dave_vetting.py` (SWEET fix — done, verified by probe)
  - `backend/orbitlab/science/pipeline.py` (SWEET flag mapping + config plumb — done)
  - `backend/orbitlab/science/science_config.py` (new key — done)
  - `backend/orbitlab/science/science_config.toml` (new key — done)
  - `backend/tests/test_small_contract_edges.py` (fixture key — done)
  - `backend/orbitlab/ml/nigraha_adapter.py` (units fix — APPLIED BUT NOT YET PROBED/TESTED — start here)
  - plus this file and `.claude/` (never commit `.claude/`)

Read these memories first if context was lost:
`~/.claude/projects/-home-aru-Student-Hackathon-Project/memory/accuracy-mission.md`,
`todo-investigate-nigraha-sweet.md`, `todo-prf-centroid-sde-calibration.md`.

Golden rule of this whole effort (user-mandated): investigate first, fix only
what evidence indicts, never blur evidence semantics to force a promotion,
never delete functionality, push when verified. Run ALL pytest commands FROM
THE REPO ROOT (`/home/aru/Student_Hackathon_Project`) — Nigraha model weights
resolve relative to CWD at `.orbitlab/models/`; running from `backend/` gives
5 spurious FileNotFoundError failures. Use `.venv/bin/pytest` (repo-root venv;
the system python is a different env without pytest).

---

## PART 1 — WHAT WAS INVESTIGATED AND PROVEN (evidence chain, do not re-derive)

### 1.1 SWEET false warning on deep planets — ROOT CAUSE FOUND AND FIXED

Symptom: confirmed hot Jupiter WASP-126 b (depth 6024 ppm) carried a
`sweet_sinusoid` warning in the round-4 live run
(`.orbitlab/benchmarks/live-planet-verification-round4/wasp-126/analysis_result.json`),
contributing (with Nigraha, below) to it being held at `borderline_tce`
instead of promoting.

Evidence chain:
1. The round-4 payload shows the warning came from the HALF-PERIOD row:
   sigma 3.726 (threshold 3.0) with sine amplitude **5.59e-5 (56 ppm)** —
   against a transit depth of **6.02e-3 (6024 ppm)**. Amplitude/depth ratio
   0.009. A 56 ppm sinusoid cannot be what BLS/TLS detected as a 6000 ppm
   transit, so this is not a sine-wave false-positive signature.
2. Our `run_sweet_test` (backend/orbitlab/science/dave_vetting.py) warned on
   bare `sigma >= 3.0`. With ~17,000 out-of-transit cadences the formal
   amplitude uncertainty `scatter/sqrt(N/2)` is tiny (~scatter/92), so ANY
   real star with ppm-level variability trips 3 sigma. Same statistical
   overconfidence class as the pooled odd/even bug fixed in `753b472`.
3. Upstream check #1 — vendored DAVE TESS pipeline
   (`.orbitlab/external/DAVE/tessPipeline/sweet.py` + `tessPipeline.py`
   line ~673): uses sigma-only too (threshold 3.5), BUT its own docstring
   admits the code is "reproduced from memory" of the original.
4. Upstream check #2 — the PUBLISHED criterion (Thompson et al. 2018, DR25
   Robovetter, arXiv:1710.06758, "Sine Wave Event Evaluation Test"): a TCE
   fails SWEET only when **SNR > 50 AND amplitude > transit depth AND
   P < 5 days**. The amplitude-vs-depth condition is the load-bearing part
   our port (and DAVE's memory-reconstruction) dropped.

Fix applied (DONE in working tree):
- `run_sweet_test` gained `amplitude_depth_fraction: float = 0.5` parameter.
  A per-period row is "warning" only when `sigma >= threshold_sigma` AND
  `amplitude/depth >= amplitude_depth_fraction`. Sigma-significant but
  depth-irrelevant sinusoids set a new top-level `variability_detected: true`
  and per-row `amplitude_depth_ratio`, with overall status "pass".
  Rationale for 0.5 not 1.0: Robovetter's 1.0 guards a hard FAIL; ours is a
  review warning, so warning at half the fail criterion is deliberately more
  sensitive while still meaningful. (Robovetter's P<5d and SNR>50 conditions
  intentionally NOT adopted: our flag is a warning, not an auto-fail, so the
  softer threshold set is the right risk trade. Documented choice — keep it.)
- Pipeline mapping (`pipeline.py` ~line 1036): status "warning" →
  `sweet_sinusoid` warning flag (message now mentions the amplitude gate);
  NEW branch: status "pass" + `variability_detected` →
  `stellar_variability_note` **info** flag (severity "info" exists in
  `_FLAG_SEVERITY_RANK`; readiness only collects hard_fail/warning, so info
  is non-blocking context by construction — verify this stays true, see 2.2).
- Config: `paper_sweet_amplitude_depth_fraction = 0.5` added to
  `science_config.toml` (with literature comment), `ScienceConfig` dataclass,
  loader, `CORE_CONFIG_KEYS`, and the fixture toml inside
  `test_small_contract_edges.py`. Pipeline passes it to `run_sweet_test` and
  emits it in the paper-grade `thresholds` payload as
  `sweet_amplitude_depth_fraction`.

Probe results (already run, working tree, seed-stable):
- Deep planet (depth 0.006) + injected 60 ppm sine at P/2 + noise:
  OLD code would warn at 13.9 sigma; NEW status "pass",
  `variability_detected: true`, max_sigma 13.86. CORRECT.
- Sinusoid masquerading as transit (BLS-style candidate whose "depth" 0.002
  equals the sine amplitude): status "warning", amplitude_depth_ratio 1.0 at
  P. The genuine sine-wave false positive is still caught. CORRECT.

### 1.2 Nigraha punishing deep transits — ROOT CAUSE FOUND, FIX APPLIED, NOT YET VERIFIED

Symptom: WASP-126 b scored 0.292 ("not-transit-like") on IN-DOMAIN 2-minute
cadence (so the cadence guard isn't the cause). L 98-59 (shallow planets)
scored 0.824. Suspicion: depth-linked.

Evidence chain (all probes used the real 10-model HDF5 ensemble via
`NigrahaService`, repo-root CWD):
1. Confounded probe: synthetic hot Jupiters scored 0.07–0.09, shallow
   planets 0.34–0.57.
2. CONTROLLED probe (only depth varies; P=3.2872, dur=0.12, teff=5800,
   radius=1.0, noise 3e-4, seed 11, 18000 points over 27 d):
   depth 0.0005→prob 0.6154; 0.001→0.9181; 0.002→0.5083; 0.004→0.3787;
   0.006→0.3097; 0.010→0.1902. Monotonic punishment of depth above 0.001.
3. Channel dissection (same deep curve, scalar overrides only):
   baseline 0.2704; Depth=6000 ("ppm") → 0.4000; Depth=0 → 0.2686;
   Depth+DepthEven+DepthOdd=6000 → 0.7000; all-0.001 → 0.2660.
   So the depth *scalar features* carry the penalty, views are
   scale-invariant by construction (`_nigraha_scale` maps every transit
   bottom to -1).
4. UNITS GROUND TRUTH — the upstream training catalog is cached locally at
   `.orbitlab/cache/nigraha_catalog/period_info-tces-dl3.csv` (the exact
   file named in `backend/orbitlab/ml/data/nigraha_norm_stats.json`,
   upstream commit c4365b41dd02b187c3210189ffe8e3ead584f4f5). Its column
   stats: `Depth` median 0.9986, min 0.2718, max 1.0; `DepthEven` median
   0.9989; `DepthOdd` median 0.9988. That is **TLS-convention mean
   in-transit flux = 1 − depth_fraction**, NOT ppm and NOT fraction.
   (`Duration` median 2.0 → hours, matches our `duration*24`; `rp_rs`
   median 0.0344 → ratio, matches our `sqrt(depth)`. Those two are correct
   as-is. The 11-feature set matches upstream KEYS per norm_stats:
   raw = Depth, Duration, rp_rs, DepthEven, DepthOdd; standardized = Teff,
   Radius, logg, Mass, lum, rho.)
   Our adapter fed `candidate.depth` (the fraction, 0.0005–0.01) — outside
   the trained 0.27–1.0 range for EVERY target, and farthest out for deep
   transits. That is the bug.

Fix applied (IN WORKING TREE, **NOT YET PROBED OR TESTED** — this is the
exact point where the session stopped):
- `backend/orbitlab/ml/nigraha_adapter.py`:
  - new helper `_tls_depth_flux(depth_fraction) -> float|None` returning
    `clip(1 - depth_fraction, 0, 1)`, None for None/non-finite input.
  - `build_nigraha_tensors` scalars changed:
    `"Depth": _scalar(depth_flux, ..., default=1.0)` where
    `depth_flux = _tls_depth_flux(candidate.depth)`;
    `"DepthEven": _scalar(_tls_depth_flux(depth_even), ..., default=depth_flux or 1.0)`;
    `"DepthOdd"` likewise. Long comment block documents the units contract
    and the 0.07-hot-Jupiter evidence.
  - `_transit_depths()` itself still returns fraction-convention measured
    depths (used only here); conversion happens at scalar assembly.

---

## PART 2 — YOUR WORK QUEUE, IN ORDER

### 2.1 FIRST ACTION: verify the Nigraha fix with the controlled probe

Run exactly this (repo root). Expectation: the depth ladder should no longer
decline monotonically; deep transits (0.004–0.01) should score at least
comparably to shallow ones, ideally all >~0.4. If deep still scores low, the
fix is wrong or incomplete — STOP and investigate before any test edits
(check: did `_scalar` receive None and silently default? print the actual
scalar tensors).

```bash
.venv/bin/python - <<'EOF'
import numpy as np, warnings
warnings.filterwarnings("ignore")
import sys; sys.path.insert(0, "backend")
from orbitlab.science.bls import TransitCandidate
from orbitlab.ml.nigraha_adapter import build_nigraha_tensors
from orbitlab.ml.nigraha_service import NigrahaService
rng = np.random.default_rng(11)
time = np.linspace(0.0, 27.0, 18000)
svc = NigrahaService()
def probe(depth):
    cand = TransitCandidate(3.2872, 0.8, 0.12, depth, 12.0, 30.0)
    phase = ((time - cand.epoch + 0.5*cand.period) % cand.period) - 0.5*cand.period
    flux = 1.0 + rng.normal(0, 3e-4, time.size)
    inn = np.abs(phase) <= 0.5*cand.duration
    flux[inn] -= depth * np.clip((0.5*cand.duration - np.abs(phase[inn]))/(0.1*cand.duration), 0, 1)
    t = build_nigraha_tensors(time, flux, cand, stellar_teff=5800., stellar_radius_solar=1.0)
    v = svc.predict(t)
    print(f"depth={depth:.4f}  prob={v.probability:.4f}  Depth_scalar={float(t.scalar_features['Depth'][0,0]):.5g}")
for d in (0.0005, 0.001, 0.002, 0.004, 0.006, 0.010):
    probe(d)
EOF
```

Pre-fix reference numbers (must beat these for deep depths):
0.0005→0.6154, 0.001→0.9181, 0.002→0.5083, 0.004→0.3787, 0.006→0.3097,
0.010→0.1902. Depth_scalar must now print ~0.9995..0.99 (i.e. 1−δ).

### 2.2 Fix the test fallout (known + likely)

```bash
.venv/bin/pytest backend/tests/test_nigraha_integration.py backend/tests/test_paper_grade_engines.py backend/tests/test_accuracy_mission_fixes.py backend/tests/test_tce_vetting.py -q
```

Known/likely breakages and the RIGHT fixes (do not paper over):
- `test_nigraha_adapter_*` in `test_nigraha_integration.py`: any assertion
  that `Depth == candidate.depth` (or Even/Odd == fraction) must flip to the
  1−δ convention. The golden-fixture forward-pass test
  (`test_nigraha_numpy_matches_original_keras_golden_fixture`) feeds fixed
  tensors directly to the network — it must NOT change (if it fails,
  something else is wrong).
- Any test asserting SWEET warns on bare sigma (search
  `grep -rn "sweet" backend/tests/`): update fixtures so a warning case has
  amplitude comparable to depth (inject sine with amplitude >= 0.5*depth) and
  add the pass+variability case. `test_paper_grade_engines.py` had SWEET
  coverage (~9 lines changed in cc8a39a) — likely needs the candidate depth
  vs injected amplitude relationship made explicit.
- Pipeline tests that enumerate flag codes may now see
  `stellar_variability_note` (info). Readiness ignores info severities
  (verified by reading `_candidate_science_readiness` — only hard_fail and
  warning branches). Also verify `_disposition` ignores info flags: it should
  only branch on hard_fail/warning codes. If any test asserts an exact flag
  LIST, add the info flag to expectations rather than removing the flag.

### 2.3 Write the NEW regression tests (these pin the science)

Add to `backend/tests/test_accuracy_mission_fixes.py`:
1. `test_sweet_requires_amplitude_comparable_to_depth`:
   - deep transit (depth 0.006) + 60 ppm sine at P/2 + gaussian noise →
     `run_sweet_test(...)["status"] == "pass"`, `variability_detected is True`,
     `max_sigma > 3`.
   - sine amplitude 0.002 == candidate depth →
     status "warning", row at P has `amplitude_depth_ratio ≈ 1`.
   (Reuse the probe code from 1.1; seeds 7 works.)
2. `test_sweet_variability_note_is_info_not_blocking`:
   build flags via `_apply_paper_grade_vetting` with a sweet payload
   `{"status": "pass", "variability_detected": True}` → expect
   `stellar_variability_note` severity "info" present, and a strong
   candidate's `_disposition` still returns `planet_candidate`.
3. `test_nigraha_depth_features_use_tls_flux_convention`:
   `build_nigraha_tensors` on a synthetic curve with depth 0.006 → assert
   `scalar_features["Depth"][0,0] == pytest.approx(0.994, abs=1e-6)`,
   DepthEven/DepthOdd within [0.97, 1.0], and (cheap distribution guard) all
   three within the upstream catalog range [0.27, 1.0].
4. (Strongly recommended, ~30 s runtime) `test_nigraha_scores_deep_and_shallow_planets_in_domain`:
   skip-if weights missing (`pytest.importorskip` pattern not applicable —
   use `Path(".orbitlab/models/nigraha").exists()` skipif); assert synthetic
   hot-Jupiter prob > 0.4 and shallow-planet prob > 0.4 with the controlled
   probe parameters above. This is the test that would have caught the units
   bug — make it exist.

### 2.4 Docs + changelog (match the established voice)

- `docs/SCIENTIFIC_METHODOLOGY.md`:
  - SWEET row in the engines table + the SWEET section: state the
    Robovetter amplitude-vs-depth gate, the 0.5 warning fraction vs 1.0
    published fail criterion, and the deliberately-not-adopted P<5d/SNR>50
    conditions with the warning-vs-fail rationale.
  - Nigraha section: document the units contract — Depth/DepthEven/DepthOdd
    are TLS-convention mean in-transit flux (1−δ, trained range 0.27–1.0),
    cite the catalog file + upstream commit; note Duration=hours,
    rp_rs=ratio verified.
  - Config dump blocks (TWO places, search `paper_sweet_sigma`): add
    `paper_sweet_amplitude_depth_fraction = 0.5`.
- `CHANGELOG.md` Unreleased→Fixed: two entries — (a) SWEET Robovetter
  amplitude gate with the WASP-126 b 56 ppm/6024 ppm example, (b) Nigraha
  depth-units fix with the 0.07-hot-Jupiter → recovered example and the
  catalog evidence.

### 2.5 Verification stack for parts 2.1–2.4 (run all, in this order)

```bash
.venv/bin/ruff check backend/
.venv/bin/pytest backend/tests/ -q                      # expect ~391+new passing, 0 failures
.venv/bin/python backend/orbitlab/benchmarks/science_benchmark.py 2>/dev/null \
  || .venv/bin/python scripts/run_orbitlab_science_benchmark.py --mode fast  # use whichever entrypoint exists; fast mode must stay 13/13
```
CRITICAL benchmark check: the sinusoidal-variability trap case must STILL be
caught (it stays borderline/rejected — the SWEET amplitude≈depth physics
guarantees it warns, but verify, don't assume).

Live unmocked re-verification (the actual acceptance test):
```bash
.venv/bin/uvicorn orbitlab.api.main:app --app-dir backend --port 8000 &   # background it
# wait for {"status":"ok"} on http://127.0.0.1:8000/api/v1/health
.venv/bin/python scripts/live_planet_verification.py --queries WASP-126 \
  --output-dir .orbitlab/benchmarks/live-planet-verification-round5
```
Takes ~35–45 min (TRICERATOPS 1M samples). PASS CRITERIA for WASP-126 b
(TCE-1, P≈3.2872):
- disposition is NOT `rejected_signal` (must be `borderline_tce` or
  `planet_candidate`);
- NO `sweet_sinusoid` flag (a `stellar_variability_note` info flag is
  acceptable and expected);
- Nigraha probability SHOULD now exceed 0.4 (threshold `paper_ml_threshold`)
  so `nigraha_low_probability` disappears — if it clears, WASP-126 b's only
  remaining warnings are red_noise/centroid_shift/catalog_contamination/
  triceratops_*_inconclusive, and since red_noise+centroid_shift are not in
  SOFT_REVIEW_WARNING_CODES it stays an honestly-reviewable borderline_tce
  with paper status "review" — that is CORRECT behavior, do not force more.
  If Nigraha still scores <0.4 on the real curve, REPORT the number honestly
  (the units fix is still right per the controlled probes) and leave the
  warning;
- the junk TCE-2 (P≈0.108 d) must STILL be `rejected_signal`;
- script exit code 0, `false_rejections: []`.
Also rerun L 98-59 (cheap insurance that shallow-planet scores didn't drop):
`--queries "L 98-59"` — expect TCE-1 (P≈3.69) ml probability ≥ ~0.8-ish and
no new hard fails. Kill the uvicorn process afterwards (`pgrep -af uvicorn`).

### 2.6 Commit + push protocol for the Nigraha/SWEET batch

- Commit ONLY the files listed at the top plus the new tests/docs. NEVER
  `.claude/`. From repo root:
- Message shape (match repo style):
  `science: SWEET amplitude-vs-depth gate and Nigraha TLS depth-units fix`
  with a body listing root causes (Robovetter criterion; TLS 1−δ convention
  with catalog evidence), probe numbers before/after, live round-5 results,
  test counts. End the body with exactly:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- Direct push to main is established practice here (`git push origin main`
  bypasses the PR rule — the user's account has bypass; two prior science
  pushes did this). Report branch + commit hash + the remote's rule-bypass
  notice back to the user.

---

## PART 3 — PRF/PSF-FIT CENTROIDING, PHASE 1A (not started; full design)

Goal: replace image-moment centroids as the PRIMARY method with a fitted
point-source model on the difference image, keeping moments as an honest
fallback. This is the NASA DV "difference image centroid offset" analogue.

Current code to read first: `backend/orbitlab/science/tpf_diagnostics.py` —
`_centroid` (moments), `_centroid_series` (per-cadence scatter for
uncertainty), `difference_image_diagnostics` (builds in/out median images,
`diff_image = out_image - in_image`, computes shift in/out, uncertainty from
cadence scatter, significance = shift/uncertainty). Consumers:
`validation.py` ValidationMetrics centroid fields, `pipeline.py` structured
flag `centroid_shift` (warning ≥2σ, stronger ≥3σ; hard fail uses
`centroid_hard_fail_pixels = 1.0` from config — read `_structured_flags` for
exact semantics BEFORE changing anything), and the frontend difference-image
panel (search frontend for `centroid_method` absence — payload is additive,
so frontend should be unaffected; verify by grep).

New module `backend/orbitlab/science/prf_centroid.py`:

```python
@dataclass(frozen=True)
class PsfFitResult:
    row: float; col: float
    row_uncertainty: float; col_uncertainty: float
    amplitude: float; background: float
    sigma_row: float; sigma_col: float
    reduced_chi2: float
    converged: bool
    n_pixels: int

def fit_point_source(image, *, pixel_noise=None, initial=None) -> PsfFitResult | None
```

Implementation requirements:
- Model: elliptical 2-D Gaussian + constant background:
  `A * exp(-((r-r0)^2/(2*sr^2) + (c-c0)^2/(2*sc^2))) + B` (axis-aligned is
  enough for 1A; document that mission PRFs replace the kernel in 1B).
- Fit with `scipy.optimize.least_squares` (loss="linear", method="trf"),
  residuals weighted by `pixel_noise` when given (per-pixel OOT scatter from
  the cube — `np.nanstd(cube[out_of_transit], axis=0)`; floor it at a small
  epsilon to avoid div-by-zero) else unweighted.
- Initial guess: image-moment centroid (reuse `_centroid`), sigma ≈ 1.2 px,
  A = max-B, B = 5th percentile. Bounds: position within image, sigmas in
  [0.3, image_size], A ≥ 0.
- Uncertainties: covariance ≈ `inv(J^T J) * 2 * cost / dof` from the
  least_squares jacobian at the solution; row/col uncertainty = sqrt of the
  diagonal entries for r0/c0. If the jacobian is singular → return None
  (caller falls back to moments).
- Reject (return None) when: <12 finite pixels, fit hits position bounds,
  non-finite covariance, or reduced_chi2 absurd (>1e3).

Integration in `difference_image_diagnostics`:
- Fit BOTH `out_image` (the target star) and the positive part of
  `diff_image` (the transit source). Offset = hypot of fitted positions;
  combined uncertainty = quadrature of both fits' positional uncertainties;
  significance = offset/uncertainty.
- Payload additions (ADDITIVE — keep every existing key so validation.py and
  the frontend keep working): `centroid_method` ("psf_fit" |
  "image_moment_fallback"), `psf_fit_out`, `psf_fit_diff` (dataclass dicts),
  `psf_offset_pixels`, `psf_offset_uncertainty_pixels`,
  `psf_offset_significance`. When BOTH fits succeed, also OVERWRITE the
  existing `centroid_shift_pixels`/`centroid_uncertainty_pixels`/
  `centroid_significance` with the PSF-fit numbers (that is the upgrade —
  the moment numbers move to `moment_centroid_*` keys for transparency).
  When either fit fails: keep current moment behavior unchanged and set
  `centroid_method = "image_moment_fallback"`.
- DO NOT add the neighbor-indictment hard-fail yet: it needs the TPF WCS to
  place TIC neighbors on pixels, and the pipeline currently does not plumb
  WCS/header into `difference_image_diagnostics`. Note it as follow-up in
  the docs (1B item). Changing flag semantics without the WCS would be
  guesswork.

Tests (`backend/tests/test_prf_centroid.py`, new):
1. Synthetic 11x11 cube, gaussian star at (5.3, 4.7), white noise, transit
   ON TARGET (scale whole PSF down in in-transit cadences): PSF fit recovers
   both positions within 0.05 px; offset significance < 2; payload
   `centroid_method == "psf_fit"`.
2. Same cube but the dip applied to a NEIGHBOR gaussian at (8.1, 2.4):
   diff-image fit lands within 0.2 px of the neighbor; offset ≈ hypot(2.8,
   2.3) ± 0.3; significance > 3. (This is the case moments smear toward the
   bright target — assert the moment offset is SMALLER than the PSF offset
   to document why the upgrade matters.)
3. Degenerate inputs (flat image, 3x3 cutout, all-NaN) → fit returns None,
   diagnostics fall back, `centroid_method == "image_moment_fallback"`, and
   every pre-existing payload key is still present.
4. Determinism: seed everything; no network, no model files.

Verification: focused tests + `test_tpf_diagnostics`-adjacent suites + fast
benchmark + ruff. Live: a single WASP-126 OR L 98-59 run and confirm the
difference-image panel payload carries `psf_fit` and sane significance; no
disposition changes expected on these two (both are on-target).

---

## PART 4 — PER-POPULATION SDE CALIBRATION (not started; full design)

Goal: `paper_tls_sde_min = 7.0` stops being a one-size threshold; the paper
gate looks up an SDE threshold calibrated to a constant false-alarm
probability for the light curve's population bin. The fixed 7.0 becomes a
FLOOR (calibration may only raise the bar, never lower it below published).

New module `backend/orbitlab/science/sde_calibration.py`:
```python
def classify_population(*, mission, cadence_seconds, baseline_days, red_noise_beta) -> str
    # bin id like "tess_short_27d_quiet"; bucket edges live in the table file
def calibrated_sde_threshold(*, mission, cadence_seconds, baseline_days,
                             red_noise_beta, config) -> dict
    # -> {"threshold": float, "bin": str, "table_version": str,
    #     "source": "calibrated" | "uncalibrated_floor"}
```
- Loads `backend/orbitlab/science/sde_calibration.toml`; missing file or
  missing bin → `{"threshold": config.paper_tls_sde_min, "source":
  "uncalibrated_floor", ...}` — NEVER raise at runtime, fail soft to floor.
- `max(table_value, config.paper_tls_sde_min)` always.
- Table schema (toml):
  ```toml
  schema_version = "orbitlab.sde_calibration.v1"
  generated = "2026-06-.."
  n_null_per_bin = 200
  fap_target = 1e-3
  seed = 42
  [bins.tess_short_27d_quiet]
  mission = "TESS"; cadence_max_s = 300; baseline_max_d = 35; beta_max = 1.3
  sde_q999 = 8.4   # the threshold
  n_null = 200
  ```
  Bucket edges: cadence ≤300 s vs >300 s (mirrors the Nigraha domain split);
  baseline ≤35 d vs >35 d; beta ≤1.3 ("quiet") vs >1.3 ("red"). Kepler:
  baseline buckets ≤90 d / >90 d. 2 missions x 2 x 2 x 2 = up to 16 bins,
  fine to ship fewer (TESS-only first) — uncovered bins fall to floor.

New script `scripts/calibrate_sde_thresholds.py`:
- CLI: `--bins tess_short_27d_quiet,... --n-null 200 --fap 1e-3 --seed 42
  --out backend/orbitlab/science/sde_calibration.toml --reduced-grid`.
- Per bin: synthesize/bootstrap null curves with the bin's cadence/baseline;
  TWO null generators, both required: (a) global permutation (kills all
  structure), (b) block bootstrap with ~0.5 d blocks (preserves red noise —
  this is what makes the "red" bins meaningfully higher). For "red" bins
  inject AR(1)-style correlated noise scaled to beta bucket midpoint.
- Search each null with the SAME machinery the pipeline uses (import
  `run_bls` / the TLS path with `period_samples=8192` reduced grid — match
  what `science_standard` does, and RECORD the grid in the table metadata;
  thresholds are only valid for comparable search effort, state this in a
  comment).
- Collect max SDE per null; threshold = quantile(1 - fap) with the small-N
  caveat: with n_null=200 you can support fap 1e-2 honestly; for 1e-3 use
  a Gumbel/GEV tail fit to the max-SDE sample (scipy.stats.genextreme.fit)
  and record both the empirical q99 and the fitted q999. Use the FITTED
  value as threshold but store both for audit.
- Smoke run for YOU (~minutes): `--bins tess_short_27d_quiet --n-null 25`
  to validate plumbing end-to-end. The FULL run (200+ nulls x all bins,
  1–3 h) is intentionally part of THIS half's duties (it is unattended
  compute): run it in the background, then commit the generated toml.

Pipeline wiring (`pipeline.py` `_apply_paper_grade_vetting`, the
`paper_tls_sde` block at ~line 995):
- Replace `config.paper_tls_sde_min` comparison with the lookup result;
  inputs available at the call site: mission_upper, and via `support` dict —
  you will need to THREAD `cadence_seconds`, `baseline_days` (compute as
  `clean_time[-1]-clean_time[0]` once, already effectively known), and
  `red_noise_beta` into `support` (it already carries
  `primary_signal_to_noise` etc., pattern established; beta is computed ~30
  lines above the support dict construction — pass it in).
- thresholds payload: replace static `tls_sde_min` with
  `tls_sde_min_floor`, `tls_sde_threshold_used`, `sde_population_bin`,
  `sde_table_version`, `sde_threshold_source`. Keep `tls_sde_min` AS WELL
  (same value as floor) so existing consumers/tests keep a stable key.
- Config: NO new numeric thresholds in code — the floor stays
  `paper_tls_sde_min` in science_config.toml; the table file carries its own
  values. Add the table path as a module constant beside CONFIG_PATH.

Tests (`backend/tests/test_sde_calibration.py`, new):
- lookup returns floor + "uncalibrated_floor" when table missing (tmp_path
  monkeypatch), when bin missing, and when table value < floor;
- returns table value when above floor with correct bin id;
- bucket-edge classification (299 s vs 301 s, beta 1.29 vs 1.31);
- toml round-trip of the generator output (run generator with --n-null 3
  in-test via subprocess or function call, parse, assert schema fields);
- pipeline wiring test: monkeypatch the table to threshold 9.0, feed a TLS
  sde of 8.0 through `_apply_paper_grade_vetting` → `paper_tls_sde` hard
  fail fires; threshold 7.0 → passes. Assert payload provenance keys.

Benchmark/live: fast benchmark must stay green (its synthetic cases are
quiet+short → bin threshold should be near 7–8.5; if a TRUE case starts
failing on SDE, the table's quiet-bin value is suspect — re-examine before
adjusting anything). Live: L 98-59 must keep all three planets' TCEs at
their current dispositions.

---

## PART 5 — MISSION PRF MODELS, PHASE 1B (lowest priority, do LAST or defer)

- Kepler: `lightkurve.prf.KeplerPRF` IS importable in this venv (verified;
  note `lightkurve.prf` only exposes KeplerPRF/SimpleKeplerPRF — there is NO
  TessPRF in lightkurve 2.6.0, do not waste time looking). Channel/column/
  row come from the TPF header (pipeline has the TPF objects in
  `mast.py`-adjacent code; you must plumb header metadata into
  `difference_image_diagnostics` — same plumbing the neighbor-indictment
  flag needs, do them together).
- TESS: PRF FITS live at
  `https://archive.stsci.edu/missions/tess/models/prf_fitsfiles/` organized
  by camera/CCD (and two epochs: sectors 1–3 vs 4+). Fetch the matching
  file, cache under `settings.calibration_dir / "prf" /` (COPY the TRILEGAL
  cache pattern in `triceratops_fpp.py`: `_calibration_dir()` indirection
  for test mockability, graceful None on network failure), record a sha256.
- Swap kernel: `fit_point_source(..., kernel=interpolated_prf)` — the 1A
  module should accept an optional callable kernel evaluated at subpixel
  offsets; Gaussian remains the universal fallback, and
  `centroid_method` gains "mission_prf_fit".
- Acceptance: same synthetic tests pass with the kernel path mocked; one
  real TESS TPF fixture (small, committed or cached) fits without error;
  offline (no network) degrades to Gaussian with honest provenance.
- If time is short: SHIP 1A + SDE without 1B. 1B changes precision, not
  semantics. Note it in CHANGELOG as future work if deferred.

---

## PART 6 — CADENCE, PUSH DISCIPLINE, AND HONESTY RULES (do not skip)

- Task-log cadence: create `.agents/task-log/` notes per task with cadence
  position (this work is tasks 1–3 of a new cadence cycle; the THIRD task
  must run the FULL suite + fast benchmark + at least one live target before
  its push, per CLAUDE.md).
- Each task pushes separately after its own focused verification (SWEET+
  Nigraha = one commit; PRF 1A = one commit; SDE = one commit (code) and the
  generated table may ride with it; 1B = one commit).
- Every commit body ends with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- NEVER commit `.claude/`, `.orbitlab/` artifacts (gitignored anyway — but
  `sde_calibration.toml` under `backend/orbitlab/science/` IS source, commit
  it), or `/tmp` logs.
- Report failures honestly: if the live Nigraha number on real WASP-126
  doesn't clear 0.4, say so with the number; the units fix stands on the
  controlled-probe evidence regardless.
- Known open review items that are NOT bugs (do not "fix"): WASP-126 b
  red_noise + centroid_shift + catalog_contamination warnings;
  triceratops_*_inconclusive gray zone; L 98-59 d rejected via
  dave_sig_sec_in_model_shift on multi-planet contamination (documented
  future work: subtract other TCEs before per-TCE ModShift).
- The user's usage budget is constrained: prefer batch edits, run the
  big compute in background, do not re-run suites idly.
