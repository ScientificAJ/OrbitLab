from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

from orbitlab.science.pipeline import MISSING_EVIDENCE_FLAG_CODES, analyze_light_curve_arrays

TruthLabel = Literal["confirmed_planet", "known_false_positive", "injected_transit", "scrambled_control"]

# Period agreement required to call a truth signal recovered (2% covers BLS
# grid spacing on these baselines without accepting harmonics, which sit at
# 50%/100% offsets).
PERIOD_MATCH_TOLERANCE = 0.02


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    group: str
    truth_label: TruthLabel
    target_id: str
    mission: str
    expected_period_days: float | None
    expected_disposition: Literal["planet_candidate", "not_planet_candidate"]
    description: str
    time: np.ndarray
    flux: np.ndarray
    # Host-star truth for the synthetic system. Passing it keeps physics
    # interpretation unlocked so radius golden checks are meaningful; cases
    # that resolve a curated known target leave these None on purpose to
    # exercise the known-target stellar merge path.
    stellar_radius_solar: float | None = None
    stellar_mass_solar: float | None = None
    stellar_teff: float | None = None
    stellar_logg: float | None = None
    # When True, a planet-truth case only counts as recovered if the pipeline
    # actually promoted it to planet_candidates in promotion-capable modes.
    # Detection without promotion is a miss, not a success.
    promotion_required: bool = False
    # Golden physics check: expected planet radius from the injected depth and
    # the true stellar radius. Catches solar-default radius corruption.
    expected_planet_radius_earth: float | None = None
    physics_tolerance_fraction: float = 0.25
    notes: tuple[str, ...] = field(default_factory=tuple)


class _BenchmarkUnavailableModel:
    def predict(self, *args, **kwargs):
        raise FileNotFoundError("benchmark intentionally runs without a registered ML artifact")


def _phase(time: np.ndarray, period: float, epoch: float) -> np.ndarray:
    return ((time - epoch + 0.5 * period) % period) - 0.5 * period


def _base_curve(seed: int, *, baseline_days: float = 27.0, cadences: int = 1800, noise: float = 1.5e-4):
    rng = np.random.default_rng(seed)
    time = np.linspace(0.0, baseline_days, cadences, dtype=np.float32)
    slow = 1.0 + 8e-5 * np.sin(2.0 * np.pi * time / 9.0)
    flux = slow + rng.normal(0.0, noise, size=time.size)
    return time.astype(np.float32), flux.astype(np.float32)


def _add_transit(
    time: np.ndarray,
    flux: np.ndarray,
    *,
    period: float,
    epoch: float,
    duration: float,
    depth: float,
) -> np.ndarray:
    injected = np.asarray(flux, dtype=np.float32).copy()
    injected[np.abs(_phase(time, period, epoch)) <= 0.5 * duration] -= depth
    return injected


def _radius_earth(depth: float, stellar_radius_solar: float) -> float:
    # Rp = sqrt(depth) * R_star; R_sun / R_earth = 109.17
    return float(np.sqrt(depth) * stellar_radius_solar * 109.17)


_SUN_LIKE = {
    "stellar_radius_solar": 1.0,
    "stellar_mass_solar": 1.0,
    "stellar_teff": 5778.0,
    "stellar_logg": 4.44,
}


def _default_cases() -> list[BenchmarkCase]:
    time_planet, flux_planet = _base_curve(10, noise=1.0e-3)
    flux_planet = _add_transit(time_planet, flux_planet, period=3.0, epoch=0.45, duration=0.12, depth=0.005)

    time_injected, flux_injected = _base_curve(11, noise=1.0e-3)
    flux_injected = _add_transit(time_injected, flux_injected, period=5.0, epoch=0.75, duration=0.16, depth=0.004)

    # TRAPPIST-1 b analog: resolves the curated known target (TIC 278892590)
    # so stellar context must come from the known-target merge, not the job.
    # Real values: P = 1.51087 d, depth ~ 0.00735, R* = 0.1192 R_sun,
    # Rp = 1.116 R_earth (Gillon et al. 2017; Agol et al. 2021).
    time_trappist, flux_trappist = _base_curve(15, cadences=4000, noise=4.0e-4)
    flux_trappist = _add_transit(
        time_trappist, flux_trappist, period=1.51087081, epoch=0.6, duration=0.035, depth=0.00735
    )

    # HAT-P-7 b analog (Kepler-2 b): P = 2.204736 d, depth ~ 0.0067,
    # R* = 1.84 R_sun, Rp ~ 16.9 R_earth (Pal et al. 2008).
    time_hatp7, flux_hatp7 = _base_curve(16, noise=2.0e-4)
    flux_hatp7 = _add_transit(
        time_hatp7, flux_hatp7, period=2.204736376, epoch=0.5, duration=0.17, depth=0.00707
    )

    time_eb, flux_eb = _base_curve(12, noise=3.0e-3)
    flux_eb = _add_transit(time_eb, flux_eb, period=4.0, epoch=0.4, duration=0.18, depth=0.012)
    flux_eb = _add_transit(time_eb, flux_eb, period=4.0, epoch=2.4, duration=0.18, depth=0.009)

    # Diluted background EB: shallow planet-like primary plus a clear
    # secondary eclipse half a period later. The secondary-eclipse gate must
    # catch it even though the primary alone looks like a healthy candidate.
    time_beb, flux_beb = _base_curve(17, noise=5.0e-4)
    flux_beb = _add_transit(time_beb, flux_beb, period=3.4, epoch=0.5, duration=0.15, depth=0.004)
    flux_beb = _add_transit(time_beb, flux_beb, period=3.4, epoch=0.5 + 1.7, duration=0.15, depth=0.002)

    # Odd/even mismatch trap: alternating eclipse depths at a 6.4 d true
    # period. A box search will lock onto 3.2 d and the odd/even depth gate
    # must fire.
    time_oe, flux_oe = _base_curve(18, noise=8.0e-4)
    flux_oe = _add_transit(time_oe, flux_oe, period=6.4, epoch=0.8, duration=0.14, depth=0.005)
    flux_oe = _add_transit(time_oe, flux_oe, period=6.4, epoch=0.8 + 3.2, duration=0.14, depth=0.003)

    # Single deep event: one isolated 1% dip must never be promoted from a
    # periodic search (single_transit gate).
    time_single, flux_single = _base_curve(19, noise=5.0e-4)
    single_window = (time_single >= 13.0) & (time_single <= 13.3)
    flux_single = flux_single.copy()
    flux_single[single_window] -= 0.01

    # False-alarm calibration controls: scrambled and pure-noise curves with
    # independent seeds. Any promotion out of these is a measured false alarm.
    scrambled_controls = []
    for seed in (13, 23, 31):
        time_scrambled, flux_scrambled = _base_curve(seed)
        rng = np.random.default_rng(seed)
        scrambled_controls.append((seed, time_scrambled, rng.permutation(flux_scrambled).astype(np.float32)))
    time_noise, flux_noise = _base_curve(29, noise=6.0e-4)

    time_variable, flux_variable = _base_curve(14, noise=1.0e-4)
    flux_variable = (flux_variable + 0.004 * np.sin(2.0 * np.pi * time_variable / 2.2)).astype(np.float32)

    return [
        BenchmarkCase(
            case_id="synthetic-confirmed-hot-planet",
            group="known_confirmed_planets",
            truth_label="confirmed_planet",
            target_id="TIC 900000001",
            mission="TESS",
            expected_period_days=3.0,
            expected_disposition="planet_candidate",
            description="High-SNR repeated transit used as a known-planet recovery sentinel.",
            time=time_planet,
            flux=flux_planet,
            promotion_required=True,
            expected_planet_radius_earth=_radius_earth(0.005, 1.0),
            **_SUN_LIKE,
        ),
        BenchmarkCase(
            case_id="synthetic-injected-mini-neptune",
            group="synthetic_injections",
            truth_label="injected_transit",
            target_id="TIC 900000002",
            mission="TESS",
            expected_period_days=5.0,
            expected_disposition="planet_candidate",
            description="Injected transit into a real-noise-shaped synthetic baseline.",
            time=time_injected,
            flux=flux_injected,
            promotion_required=True,
            expected_planet_radius_earth=_radius_earth(0.004, 1.0),
            **_SUN_LIKE,
        ),
        BenchmarkCase(
            case_id="trappist-1b-analog-known-target",
            group="known_confirmed_planets",
            truth_label="confirmed_planet",
            target_id="TIC 278892590",
            mission="TESS",
            expected_period_days=1.51087081,
            expected_disposition="planet_candidate",
            description=(
                "TRAPPIST-1 b analog at the real catalog period and depth; stellar context must "
                "come from the curated known-target entry (M-dwarf, 0.1192 R_sun), so the "
                "recovered radius must be Earth-sized, not the 9x solar-default corruption."
            ),
            time=time_trappist,
            flux=flux_trappist,
            promotion_required=True,
            expected_planet_radius_earth=_radius_earth(0.00735, 0.1192),
            physics_tolerance_fraction=0.30,
            notes=("Real-planet parameters: TRAPPIST-1 b, P=1.51087 d, Rp=1.116 R_earth.",),
        ),
        BenchmarkCase(
            case_id="hat-p-7b-analog-known-target",
            group="known_confirmed_planets",
            truth_label="confirmed_planet",
            target_id="KIC 10666592",
            mission="Kepler",
            expected_period_days=2.204736376,
            expected_disposition="planet_candidate",
            description=(
                "HAT-P-7 b analog on the Kepler path; known-target stellar context (1.84 R_sun) "
                "must yield a hot-Jupiter radius near 16.9 R_earth."
            ),
            time=time_hatp7,
            flux=flux_hatp7,
            promotion_required=True,
            expected_planet_radius_earth=_radius_earth(0.00707, 1.84),
            notes=("Real-planet parameters: HAT-P-7 b, P=2.204736 d, Rp~16.9 R_earth.",),
        ),
        BenchmarkCase(
            case_id="synthetic-eclipsing-binary",
            group="known_false_positives",
            truth_label="known_false_positive",
            target_id="TIC 900000003",
            mission="TESS",
            expected_period_days=4.0,
            expected_disposition="not_planet_candidate",
            description="Primary and secondary eclipse trap.",
            time=time_eb,
            flux=flux_eb,
            **_SUN_LIKE,
        ),
        BenchmarkCase(
            case_id="background-eb-secondary-trap",
            group="known_false_positives",
            truth_label="known_false_positive",
            target_id="TIC 900000006",
            mission="TESS",
            expected_period_days=3.4,
            expected_disposition="not_planet_candidate",
            description="Diluted background eclipsing binary with a clear secondary eclipse.",
            time=time_beb,
            flux=flux_beb,
            **_SUN_LIKE,
        ),
        BenchmarkCase(
            case_id="odd-even-depth-mismatch-trap",
            group="known_false_positives",
            truth_label="known_false_positive",
            target_id="TIC 900000007",
            mission="TESS",
            expected_period_days=None,
            expected_disposition="not_planet_candidate",
            description="Alternating eclipse depths; the odd/even gate must reject the half-period alias.",
            time=time_oe,
            flux=flux_oe,
            **_SUN_LIKE,
        ),
        BenchmarkCase(
            case_id="single-deep-event-artifact",
            group="known_false_positives",
            truth_label="known_false_positive",
            target_id="TIC 900000008",
            mission="TESS",
            expected_period_days=None,
            expected_disposition="not_planet_candidate",
            description="One isolated deep dip; periodic promotion must be blocked by the transit-count gate.",
            time=time_single,
            flux=flux_single,
            **_SUN_LIKE,
        ),
        *[
            BenchmarkCase(
                case_id=(
                    "scrambled-control-light-curve"
                    if index == 0
                    else f"scrambled-control-light-curve-seed{seed}"
                ),
                group="scrambled_controls",
                truth_label="scrambled_control",
                target_id=f"TIC 90000000{4 if index == 0 else index + 8}",
                mission="TESS",
                expected_period_days=None,
                expected_disposition="not_planet_candidate",
                description=f"Time-order-scrambled control light curve (seed {seed}).",
                time=scrambled_time,
                flux=scrambled_flux,
                **_SUN_LIKE,
            )
            for index, (seed, scrambled_time, scrambled_flux) in enumerate(scrambled_controls)
        ],
        BenchmarkCase(
            case_id="pure-noise-control",
            group="scrambled_controls",
            truth_label="scrambled_control",
            target_id="TIC 900000012",
            mission="TESS",
            expected_period_days=None,
            expected_disposition="not_planet_candidate",
            description="Pure white-noise control; any promotion is a measured false alarm.",
            time=time_noise,
            flux=flux_noise,
            **_SUN_LIKE,
        ),
        BenchmarkCase(
            case_id="sinusoidal-stellar-variability",
            group="stellar_variability_cases",
            truth_label="known_false_positive",
            target_id="TIC 900000005",
            mission="TESS",
            expected_period_days=None,
            expected_disposition="not_planet_candidate",
            description="Large sinusoidal variability trap.",
            time=time_variable,
            flux=flux_variable,
            **_SUN_LIKE,
        ),
    ]


def _select_best_tce(tces: list[Any], expected_period_days: float | None) -> dict[str, Any] | None:
    dict_tces = [tce for tce in tces if isinstance(tce, dict)]
    if not dict_tces:
        return None
    if expected_period_days:
        for tce in dict_tces:
            period = tce.get("period_days")
            if isinstance(period, (int, float)) and period > 0:
                if abs(float(period) - expected_period_days) / expected_period_days <= PERIOD_MATCH_TOLERANCE:
                    return tce
    return dict_tces[0]


def _physics_check(case: BenchmarkCase, best_tce: dict[str, Any] | None) -> dict[str, Any] | None:
    if case.expected_planet_radius_earth is None or not isinstance(best_tce, dict):
        return None
    physics = best_tce.get("physics") if isinstance(best_tce.get("physics"), dict) else {}
    measured = physics.get("planet_radius_earth")
    locked = bool(physics.get("interpretation_locked"))
    error_fraction = None
    if isinstance(measured, (int, float)) and np.isfinite(measured) and case.expected_planet_radius_earth:
        error_fraction = abs(float(measured) - case.expected_planet_radius_earth) / case.expected_planet_radius_earth
    ok = (
        not locked
        and error_fraction is not None
        and error_fraction <= case.physics_tolerance_fraction
    )
    return {
        "expected_planet_radius_earth": case.expected_planet_radius_earth,
        "measured_planet_radius_earth": float(measured) if isinstance(measured, (int, float)) else None,
        "radius_error_fraction": error_fraction,
        "tolerance_fraction": case.physics_tolerance_fraction,
        "interpretation_locked": locked,
        "stellar_context_source": physics.get("stellar_context_source"),
        "ok": ok,
    }


def _case_result(case: BenchmarkCase, *, vetting_mode: str) -> dict[str, Any]:
    payload = analyze_light_curve_arrays(
        target_id=case.target_id,
        mission=case.mission,
        time=case.time,
        flux=case.flux,
        stellar_radius_solar=case.stellar_radius_solar,
        stellar_mass_solar=case.stellar_mass_solar,
        stellar_teff=case.stellar_teff,
        stellar_logg=case.stellar_logg,
        vetting_mode=vetting_mode,
        max_candidates=2,
        nigraha_service=_BenchmarkUnavailableModel(),
    )
    tces = payload.get("tces") or []
    planet_candidates = payload.get("planet_candidates") or []
    best_tce = _select_best_tce(tces, case.expected_period_days)
    recovered_period = best_tce.get("period_days") if isinstance(best_tce, dict) else None
    period_error = (
        abs(float(recovered_period) - case.expected_period_days) / case.expected_period_days
        if recovered_period is not None and case.expected_period_days
        else None
    )
    flags = best_tce.get("flags", []) if isinstance(best_tce, dict) else []
    hard_fail_codes = {
        str(flag.get("code"))
        for flag in flags
        if isinstance(flag, dict) and flag.get("severity") == "hard_fail"
    }
    evidence_against_codes = hard_fail_codes - set(MISSING_EVIDENCE_FLAG_CODES)
    best_disposition = best_tce.get("disposition") if isinstance(best_tce, dict) else None
    promoted = bool(planet_candidates)

    signal_recovered = bool(best_tce) and not evidence_against_codes
    if case.expected_period_days:
        signal_recovered = signal_recovered and period_error is not None and period_error <= PERIOD_MATCH_TOLERANCE

    if case.expected_disposition == "planet_candidate":
        recovered = signal_recovered
        if case.promotion_required:
            if vetting_mode == "paper":
                # Paper mode without ML artifacts / network engines blocks
                # promotion on missing evidence; the honest expectation is a
                # reviewable TCE, never a rejected_signal false positive.
                recovered = signal_recovered and best_disposition != "rejected_signal"
            else:
                recovered = signal_recovered and promoted
    else:
        recovered = not promoted

    escaped = case.expected_disposition == "not_planet_candidate" and promoted
    near_escape = (
        case.expected_disposition == "not_planet_candidate"
        and not promoted
        and best_disposition == "borderline_tce"
        and not hard_fail_codes
    )
    missed = case.expected_disposition == "planet_candidate" and not recovered
    physics_check = _physics_check(case, best_tce)
    engine_status = payload.get("engine_status") or {}
    engine_failures = {
        name: status
        for name, status in engine_status.items()
        if isinstance(status, dict) and status.get("status") in {"failed", "inconclusive", "unstable_result"}
    }
    return {
        "case": asdict(case) | {"time": None, "flux": None},
        "truth_label": case.truth_label,
        "expected_disposition": case.expected_disposition,
        "recovered": recovered,
        "signal_recovered": signal_recovered,
        "promoted_candidate_recovered": promoted,
        "promotion_required": case.promotion_required,
        "false_alarm_escaped": escaped,
        "near_escape": near_escape,
        "missed_known_planet": missed,
        "best_disposition": best_disposition,
        "planet_candidate_count": len(planet_candidates),
        "tce_count": len(tces),
        "recovered_period_days": recovered_period,
        "period_error_fraction": period_error,
        "evidence_against_codes": sorted(evidence_against_codes),
        "missing_evidence_codes": sorted(hard_fail_codes & set(MISSING_EVIDENCE_FLAG_CODES)),
        "physics_check": physics_check,
        "engine_failures": engine_failures,
        "flags": flags,
    }


def _rate(results: list[dict[str, Any]], predicate, success_key: str = "recovered") -> float | None:
    subset = [result for result in results if predicate(result)]
    if not subset:
        return None
    return sum(bool(result[success_key]) for result in subset) / len(subset)


def run_science_benchmark(
    *,
    cases: list[BenchmarkCase] | None = None,
    vetting_mode: Literal["fast", "deep", "paper"] = "fast",
) -> dict[str, Any]:
    selected_cases = cases or _default_cases()
    results = [_case_result(case, vetting_mode=vetting_mode) for case in selected_cases]
    engine_failure_summary: dict[str, int] = {}
    for result in results:
        for name in result["engine_failures"]:
            engine_failure_summary[name] = engine_failure_summary.get(name, 0) + 1
    false_alarm_escape_list = [row["case"]["case_id"] for row in results if row.get("false_alarm_escaped")]
    missed_known_planets = [row["case"]["case_id"] for row in results if row.get("missed_known_planet")]
    physics_failures = [
        row["case"]["case_id"]
        for row in results
        if isinstance(row.get("physics_check"), dict) and not row["physics_check"]["ok"]
    ]
    # The harness fails loudly: a benchmark that cannot fail is not evidence.
    status = "passed" if not (false_alarm_escape_list or missed_known_planets or physics_failures) else "failed"
    return {
        "status": status,
        "engine": "orbitlab_science_benchmark",
        "vetting_mode": vetting_mode,
        "case_count": len(results),
        "known_planet_recovery_rate": _rate(results, lambda row: row["truth_label"] == "confirmed_planet"),
        "false_positive_rejection_rate": _rate(
            results,
            lambda row: row["truth_label"] in {"known_false_positive", "scrambled_control"},
        ),
        "injected_transit_recovery_rate": _rate(results, lambda row: row["truth_label"] == "injected_transit"),
        "promoted_planet_recovery_rate": _rate(
            results,
            lambda row: row["expected_disposition"] == "planet_candidate" and row["promotion_required"],
            success_key="promoted_candidate_recovered",
        ),
        "false_alarm_escape_list": false_alarm_escape_list,
        "missed_known_planets": missed_known_planets,
        "near_escape_list": [row["case"]["case_id"] for row in results if row.get("near_escape")],
        "physics_failures": physics_failures,
        "unstable_candidates": [
            row["case"]["case_id"]
            for row in results
            if row.get("period_error_fraction") is not None
            and row["period_error_fraction"] > PERIOD_MATCH_TOLERANCE
        ],
        "engine_failure_summary": engine_failure_summary,
        "results": results,
    }


def benchmark_report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# OrbitLab Science Benchmark Report",
        "",
        f"- Status: `{report.get('status')}`",
        f"- Vetting mode: `{report.get('vetting_mode')}`",
        f"- Case count: `{report.get('case_count')}`",
        f"- Known planet recovery rate: `{report.get('known_planet_recovery_rate')}`",
        f"- False positive rejection rate: `{report.get('false_positive_rejection_rate')}`",
        f"- Injected transit recovery rate: `{report.get('injected_transit_recovery_rate')}`",
        f"- Promoted planet recovery rate: `{report.get('promoted_planet_recovery_rate')}`",
        "",
        "## Escapes And Misses",
        "",
        f"- False alarm escape list: `{report.get('false_alarm_escape_list')}`",
        f"- Missed known planets: `{report.get('missed_known_planets')}`",
        f"- Near escapes (reviewable, not promoted): `{report.get('near_escape_list')}`",
        f"- Physics golden-check failures: `{report.get('physics_failures')}`",
        f"- Unstable candidates: `{report.get('unstable_candidates')}`",
        "",
        "## Cases",
        "",
        "| Case | Truth | Expected | Best disposition | Promoted | Signal recovered | Physics | Recovered |",
        "| --- | --- | --- | --- | ---: | --- | --- | --- |",
    ]
    for result in report.get("results", []):
        case = result.get("case", {})
        physics_check = result.get("physics_check")
        if isinstance(physics_check, dict):
            physics_cell = "ok" if physics_check.get("ok") else "FAIL"
        else:
            physics_cell = "-"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(case.get("case_id")),
                    str(result.get("truth_label")),
                    str(result.get("expected_disposition")),
                    str(result.get("best_disposition")),
                    str(result.get("planet_candidate_count")),
                    str(result.get("signal_recovered")),
                    physics_cell,
                    str(result.get("recovered")),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def write_benchmark_reports(report: dict[str, Any], output_dir: str | Path) -> dict[str, str]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / "benchmark_report.json"
    md_path = root / "benchmark_report.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(benchmark_report_markdown(report), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}
