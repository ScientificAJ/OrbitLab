# OrbitLab: real core issues for a NASA-grade exoplanet system

You’re right. I made the answer heavier than the project and spent too much time polishing the warning label instead of opening the engine bay. That was not useful enough.

Here is the corrected version: **not nomenclature-first, not legal-caveat-first, but actual project engineering.**

The biggest issue is **not the name “paper-grade.”** The biggest issue is this:

> OrbitLab currently detects and vets signals, but it does not yet prove how often it is right, how often it misses real planets, and how often false positives escape.

That is the real monster under the bed. Not wording. Not branding. The beast is **measured reliability**.

NASA-style thinking would ask:

```text
Does this system survive real known planets?
Does it reject real known false positives?
Does it recover injected planets?
Does it fail loudly when evidence is incomplete?
Does it produce the same answer on another machine?
Can we explain exactly why a signal passed or failed?
```

That is the correct project target.

---

# 1. The main missing layer: benchmark truth testing

Right now, OrbitLab has strong science modules:

```text
MAST product ingestion
TPF extraction
Wotan detrending
BLS/TLS search
DAVE ModShift
TRICERATOPS
Nigraha ML
catalog context
evidence display
```

But the system needs a **truth-benchmark harness**.

NASA-grade does not mean “we used TLS and TRICERATOPS.” It means:

```text
We tested the full pipeline against known truth sets.
```

Kepler’s DR25 catalog work measured completeness and reliability using simulated data and Robovetter behavior, and NASA Exoplanet Archive hosts completeness/reliability products for Kepler pipeline evaluation. ([arXiv][1])

OrbitLab needs this:

```text
backend/orbitlab/benchmarks/
  confirmed_planets/
  known_false_positives/
  injected_transits/
  scrambled_controls/
  contaminated_apertures/
  stellar_variability_cases/
```

And a command:

```bash
python scripts/run_orbitlab_science_benchmark.py
```

Output:

```text
known_planet_recovery_rate
false_positive_rejection_rate
injected_transit_recovery_rate
false_alarm_escape_list
missed_known_planets
unstable_candidates
engine_failure_summary
```

This is the single biggest upgrade. It turns OrbitLab from “smart detector” into “measured scientific instrument.”

---

# 2. OrbitLab needs an adversarial false-positive zoo

The project should not only ask:

```text
Can I find a planet-like dip?
```

It should ask:

```text
Can a fake planet fool me?
```

That means building a test zoo:

```text
eclipsing binary
background eclipsing binary
nearby diluted eclipsing binary
stellar rotation harmonic
pulsating star
instrumental jump
single bad sector
scattered light artifact
momentum dump-like artifact
aperture edge contamination
odd/even depth mismatch
secondary eclipse
```

Current OrbitLab has checks for many of these individually, but it needs a **formal false-positive challenge suite**.

A NASA/Mark-Rober-style test would be visual and brutal:

```text
100 fake traps enter.
How many escape as candidates?
Which module failed to catch them?
```

That is the kind of demo judges remember.

Not “our app has TLS.”

More like:

> “We tried to trick OrbitLab with 500 fake planet signals. Here is exactly which ones survived and why.”

That is the hammer.

---

# 3. The system needs injection-recovery, not only detection

Detection alone is incomplete.

OrbitLab should inject synthetic transits into real light curves or pixel-level data and then run the entire pipeline. Kepler pipeline sensitivity studies injected simulated transits into pixel-level data and measured recovery rate, showing that detection efficiency can depend on period and other pipeline behavior. ([arXiv][2])

OrbitLab needs:

```text
inject_transit(
  period,
  depth,
  duration,
  epoch,
  impact_parameter,
  limb_darkening,
  noise_context
)
```

Then measure:

```text
was_recovered
recovered_period_error
recovered_epoch_error
recovered_depth_error
passed_vetting
failed_gate
```

The result should become a heatmap:

```text
Recovery probability by:
  period
  depth
  stellar magnitude
  noise level
  sector count
  cadence count
```

This is where OrbitLab becomes serious.

Without this, it can say:

```text
I found a signal.
```

With this, it can say:

```text
For this target/noise regime, signals like this are recoverable with X% sensitivity under the current pipeline.
```

That is a massive scientific upgrade.

---

# 4. Multi-sector behavior is not optional for serious candidates

A single product or single-sector workflow is good for interactive analysis, but serious exoplanet vetting needs sector consistency.

The TESS SPOC system produces TPFs, light curves, and associated products, and TESS data products include light curves with systematics removal/cotrending from SPOC algorithms. ([MAST][3])

OrbitLab should ask:

```text
Does the period remain stable across sectors?
Does epoch drift?
Does depth change suspiciously?
Does the signal disappear in one sector?
Does the candidate survive stitched analysis?
Does the aperture contamination change sector by sector?
```

Add a sector consistency report:

```text
sector_evidence:
  sector_id
  transit_count
  period_support
  depth_ppm
  duration_hours
  snr
  centroid_offset
  aperture_score
  contamination_warning
```

Then final verdict:

```text
multi_sector_status:
  consistent
  inconsistent
  single_sector_only
  insufficient_data
```

This matters because a beautiful folded curve from one sector can be a liar wearing a lab coat.

---

# 5. Centroid and contamination logic needs to become stronger

OrbitLab’s difference image and centroid logic is useful, but not enough for NASA-grade source localization.

TESS DV products include centroid and difference-image style diagnostics as part of the data validation product family, so OrbitLab should move closer to that evidence style. ([MAST][4])

Current OrbitLab:

```text
image moment centroid
difference image
nearby source screen
```

Needed upgrade:

```text
per-sector difference images
centroid uncertainty estimate
catalog-coordinate comparison
nearby-source likelihood ranking
aperture contamination score
target-vs-neighbor source probability
```

Better output:

```text
source_localization:
  likely_source: target / nearby_star / unknown
  centroid_offset_arcsec
  centroid_offset_sigma
  nearest_capable_contaminant
  contaminant_depth_possible
  aperture_overlap_fraction
  verdict: clean / suspicious / contaminated / unreliable
```

This is not naming. This is the difference between:

```text
dip came from target star
```

and:

```text
dip may be from the star next door photobombing the aperture
```

Huge difference.

---

# 6. TRICERATOPS should use aperture-aware context

Your own methodology already identifies this correctly: OrbitLab calls real TRICERATOPS, but does not fully pass aperture context.

TRICERATOPS is designed to compute false-positive probability and nearby false-positive probability using transit data and nearby field-star context; published validation criteria include FPP < 0.015 and NFPP < 0.001. ([Astrophysics Data System][5])

So the improvement is not “rename TRICERATOPS result.”

The improvement is:

```text
Pass actual selected aperture information.
Run nearby-source depth calculations.
Store scenario probabilities.
Run repeated sampling to estimate stability.
Expose whether follow-up constraints were used.
```

Required output:

```text
triceratops:
  fpp
  nfpp
  fpp_uncertainty
  nfpp_uncertainty
  samples
  aperture_used: true/false
  calc_depths_used: true/false
  contrast_curve_used: true/false
  scenario_probabilities
```

Then the system knows whether FPP is strong evidence or partial evidence.

---

# 7. Detrending must be stress-tested

The Wotan biweight method is fine. The problem is relying on one cleaned version too heavily.

OrbitLab should compare:

```text
raw SAP
PDCSAP if available
Wotan biweight
alternate Wotan windows
transit-masked detrending
CBV/cotrending path where possible
```

Then report:

```text
detrending_sensitivity:
  period_stable
  depth_stable
  epoch_stable
  snr_stable
  methods_tested
  worst_case_result
```

Why this matters:

A real signal should not vanish just because the flattening window changed slightly. If it does, the system should say:

```text
This candidate is detrending-sensitive.
```

That is a real scientific warning.

---

# 8. ML needs domain-awareness, not just probability

Nigraha/AstroNet-style ML is useful, but it should not be treated as a magical detector oracle.

ML should answer:

```text
Does this look like examples the model was trained to understand?
```

Not only:

```text
planet probability = 0.67
```

Add:

```text
ml_evidence:
  model_score
  calibrated_score
  out_of_distribution_score
  model_training_domain
  tensor_checksum
  artifact_checksum
  disagreement_with_physics
  disagreement_with_vetting
```

If ML says “planet” but DAVE says secondary eclipse, OrbitLab should not average them like soup.

It should say:

```text
ML support conflicts with vetting evidence.
```

That is mature.

---

# 9. Engine failure handling should be more scientific

Current strict blocking is good, but the system needs better failure categories.

Do not collapse everything into pass/fail.

Use:

```text
passed
failed
not_assessed
engine_unavailable
insufficient_data
unstable_result
inconclusive
```

Example:

```text
DAVE unavailable
```

does not mean:

```text
signal failed DAVE
```

It means:

```text
DAVE evidence missing, promotion incomplete
```

That distinction matters scientifically.

---

# 10. The correct goal

The goal should not be “build a NASA replacement.”

That is too broad and not the point.

The correct goal is:

```text
Build OrbitLab as a transparent exoplanet signal investigation system that can take real archive data, detect TCEs, challenge them against false-positive traps, measure its own recovery/rejection performance, and produce a reproducible evidence packet for follow-up review.
```

In simpler terms:

> OrbitLab should become the **MythBusters lab for exoplanet signals**.

Every candidate goes through traps:

```text
Is the dip real?
Is it periodic?
Does it survive detrending?
Does it survive other apertures?
Does it appear across sectors?
Is there a secondary eclipse?
Are odd/even depths suspicious?
Could a nearby star mimic it?
Does centroid evidence point away?
Does TRICERATOPS agree?
Does ML agree?
Would injected planets of similar size be recovered?
```

If it survives, OrbitLab should not scream “planet found.”

It should say:

```text
This signal survived OrbitLab's current evidence gauntlet and deserves follow-up.
```

That is strong. That is honest. That is usable.

---

# Practical next build plan

## Phase 1: Science benchmark harness

Create:

```text
scripts/run_science_benchmark.py
backend/orbitlab/benchmarks/
```

Benchmark groups:

```text
known_confirmed_planets
known_false_positives
synthetic_injections
scrambled_controls
contaminated_cases
```

Output:

```text
benchmark_report.json
benchmark_report.md
```

---

## Phase 2: Injection-recovery module

Add:

```text
backend/orbitlab/science/injection_recovery.py
```

Functions:

```python
inject_box_transit()
inject_tls_like_transit()
run_recovery_grid()
summarize_recovery()
```

Output:

```text
recovery_probability
minimum_detectable_depth
period_sensitivity
pipeline_sensitivity_score
```

---

## Phase 3: Multi-sector consistency

Add:

```text
backend/orbitlab/science/sector_stitching.py
backend/orbitlab/science/sector_consistency.py
```

Output:

```text
sector_by_sector_period
sector_by_sector_depth
sector_by_sector_centroid
sector_consistency_score
```

---

## Phase 4: False-positive trap suite

Add generated test cases:

```text
eclipsing_binary
background_eclipsing_binary
sinusoidal_variability
single_event_artifact
odd_even_mismatch
secondary_eclipse
neighbor_contamination
```

Every trap should be something OrbitLab must defeat.

---

## Phase 5: Evidence packet export

For each TCE, export:

```text
evidence_packet/
  manifest.json
  light_curve.csv
  folded_curve.csv
  periodogram.csv
  vetting.json
  catalog_context.json
  triceratops.json
  ml_evidence.json
  plots/
  final_disposition.md
```

This is the judge-facing gold.

---

# The sharper final positioning

OrbitLab should be described as:

```text
A real-data exoplanet TCE investigation and follow-up triage workbench that combines archive product extraction, transit search, vetting diagnostics, contamination analysis, ML support, and benchmarked reliability testing into a reproducible evidence packet.
```

That is the correct beast.

Not smaller than NASA-grade. More realistic and more powerful for this project.

NASA-grade direction does not mean copying SPOC brick by brick. It means adopting the discipline:

```text
truth sets
false-positive traps
injection recovery
sector consistency
reproducibility
evidence transparency
measured reliability
```

That is where OrbitLab should go.

[1]: https://arxiv.org/abs/1710.06758?utm_source=chatgpt.com "Planetary Candidates Observed by Kepler. VIII. A Fully Automated Catalog With Measured Completeness and Reliability Based on Data Release 25"
[2]: https://arxiv.org/abs/1605.05729?utm_source=chatgpt.com "Measuring Transit Signal Recovery in the Kepler Pipeline. III. Completeness of the Q1-Q17 DR24 Planet Candidate Catalogue, with Important Caveats for Occurrence Rate Calculations"
[3]: https://archive.stsci.edu/hlsp/tess-spoc?utm_source=chatgpt.com "TESS-SPOC - MAST Archive"
[4]: https://archive.stsci.edu/files/live/sites/mast/files/home/missions-and-data/active-missions/tess/_documents/EXP-TESS-ARC-ICD-TM-0014-Rev-F.pdf?utm_source=chatgpt.com "TESS Science Data Products Description Document"
[5]: https://ui.adsabs.harvard.edu/abs/2021AJ....161...24G/abstract?utm_source=chatgpt.com "Vetting of 384 TESS Objects of Interest with ..."

---

# Mark Rober-style engineering handoff

Alright, let’s look at this handover. If Mark Rober walked into the room, grabbed a marker, and looked at this spec for a NASA-grade exoplanet workbench, the first thing he’d say is:

*"The engineering here is super clean. It actually talks to real hardware—the spacecraft data—instead of just playing in a sandbox. But if we are telling people this is an 'Accuracy Paper-Grade' machine, we have a few massive blind spots where the physics of the universe is going to bite us in the butt. We’ve built an incredibly precise digital caliper, but we're measuring a wobbling piece of Jell-O."*

To get this to a true NASA-flight-readiness level, we need to bridge the gap between "good software engineering" and "relentless physical reality."

Here is the breakdown of the core scientific issues with the 2026 OrbitLab implementation, what our actual engineering goals should be, and the practical, clever ways to fix them.

---

## 1. The "Square Peg, Round Hole" Transit Problem

### The Issue

OrbitLab uses Astropy’s Box Least Squares (BLS) as its broad periodogram and residual multi-candidate engine. BLS assumes transits look like a perfect cardboard box dropped into the light curve.
But physics isn’t a box. Stars are spheres, and they have **limb darkening**—they are brighter in the center than at the edges. When a planet crosses, the dip is a smooth, elegant curve, not a box. While the primary search uses Transit Least Squares (TLS) to handle this properly, your *multi-candidate residual search* drops back to BLS.
If a star has multiple planets, BLS will completely miss or miscalculate the shallow, curved signatures of the smaller siblings left in the residuals.

### The NASA/Rober Goal

**Don't leave a planet behind.** The search loop needs to treat the universe dynamically. If you find a giant Jupiter-sized planet with TLS, you don't just subtract a box and look for the leftovers with a box tool. You must use an analytical limb-darkened model template for the residual search loop.

```text
[BLS Box Model:   |___|  <- Misses grazing transits & limb-darkening shape]
[Real Physics:    \_/    <- What we actually need to look for in residuals]
```

---

## 2. The Aperture Blindfold (The TRICERATOPS Flaw)

### The Issue

This is a classic "almost-had-it" engineering disconnect. OrbitLab pulls down the real Target Pixel Files (TPFs) so the user can see the actual pixels lighting up. That’s awesome. But then, when it passes data to TRICERATOPS to calculate the False Positive Probability (FPP), it just sends a flat, 1D binned light curve.

TRICERATOPS is a spatial-statistical beast. It wants to know exactly *which* pixels you calculated that flux from so it can determine if a background eclipsing binary 3 arcseconds away is bleeding into your custom mask. By stripping the pixel-level aperture mask before feeding TRICERATOPS, you are throwing away your best shield against background impostors.

### The NASA/Rober Goal

**Max out the data loop.** Feed the actual pipeline-derived or user-selected `aperture_mask` straight into TRICERATOPS via its `calc_depths` path. If the code doesn’t tell the math *where* it’s looking on the detector sky, the math can’t tell you if you’re being tricked by a nearby star.

---

## 3. The Stationary Target Illusion (The Centroid Trap)

### The Issue

The implementation calculates a basic center-of-mass (flux-weighted moment) centroid for the target star. If the centroid shifts during a transit, OrbitLab flags a warning.
Here’s the catch: stars don't sit perfectly still on the detector. The spacecraft jitters, thermal changes cause breathing in the optics, and the fine-guidance sensors drop corrections.

A simple image moment can’t distinguish between *"the spacecraft shook by 0.01 pixels"* and *"the light shifted because a background star dropped in brightness."* NASA pipelines use a Pixel Response Function (PRF) fit—a mathematical model of how a point source of light spills across a grid of pixels—to track the absolute micro-position of the star.

### The NASA/Rober Goal

**Measure against a solid baseline, not a moving boat.** Instead of a naive moment calculation that gets thrown off by background noise fluctuations, we need a local, lightweight PRF-triage model or a cross-correlation matrix across the out-of-transit frames to build a dynamic baseline of spacecraft motion.

---

## 4. The "One Size Fits All" Stellar Guesswork

### The Issue

If a user queries a target that doesn't have stellar radius, mass, or effective temperature ($T_{eff}$) listed in the TIC/Gaia catalog, OrbitLab plugs in solar-like constants ($1.0 \, R_{\odot}$, $1.0 \, M_{\odot}$) to keep the math from crashing.
That sounds fine for an app, but in exoplanet physics, it’s a disaster. If your target is actually an M-dwarf (a tiny star a fraction of the size of our sun), plugging in solar values means your calculated planet radius will be off by a factor of 10! You'll classify an Earth-sized rock as a gas giant, or vice versa, and completely ruin your habitability calculations.

### The NASA/Rober Goal

**Fail smart, or estimate with guards.** If the catalog doesn't know the star, you can't assume it's our Sun. The system should use an empirical stellar property relation lookup table based on whatever sparse data *is* available (like Gaia broadband colors or $G-RP$ color indices). If that still fails, block the physics engine entirely and put a giant, clear warning: **"Physical Properties Locked: Stellar Parentage Unknown."**

---

# Technical Action Plan for Maintainers

To turn these insights into code, focus on upgrading these specific architectural components:

## A. The Multi-Planet Residual Engine (`backend/orbitlab/science/bls.py`)

Upgrade the multi-candidate loop to iteratively apply a limb-darkened transit profile subtraction rather than a simple box mask. Ensure that the residual arrays passed into subsequent search passes maintain the physical shape of the original stellar limb-darkening coefficients ($u_1, u_2$).

## B. Aperture Integration (`backend/orbitlab/science/triceratops_fpp.py`)

Rewrite the TRICERATOPS wrapper to ingest the bounding coordinate arrays of the chosen pixel aperture.

```python
# Target implementation fix
# Instead of: target = tr.target(ID=tic_id, sectors=sectors)
# Move to an aperture-aware target initialization:
target = tr.target(ID=tic_id, sectors=sectors)
target.calc_depths(tdepth=observed_depth, aperture=user_selected_mask)
```

## C. Contextual Safeguards (`backend/orbitlab/science/physics.py`)

Introduce a strict verification check prior to executing the Kopparapu Habitable Zone equations. If stellar parameter uncertainties span more than 50% variance, or if default fallback constants are active, the system must raise an explicit `IncompleteStellarContextError` to safeguard the downstream analysis results.
