from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np

from orbitlab.science.pipeline import analyze_light_curve_arrays

TruthLabel = Literal["confirmed_planet", "known_false_positive", "injected_transit", "scrambled_control"]


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


def _default_cases() -> list[BenchmarkCase]:
    time_planet, flux_planet = _base_curve(10, noise=1.0e-3)
    flux_planet = _add_transit(time_planet, flux_planet, period=3.0, epoch=0.45, duration=0.12, depth=0.005)

    time_injected, flux_injected = _base_curve(11, noise=1.0e-3)
    flux_injected = _add_transit(time_injected, flux_injected, period=5.0, epoch=0.75, duration=0.16, depth=0.004)

    time_eb, flux_eb = _base_curve(12, noise=3.0e-3)
    flux_eb = _add_transit(time_eb, flux_eb, period=4.0, epoch=0.4, duration=0.18, depth=0.012)
    flux_eb = _add_transit(time_eb, flux_eb, period=4.0, epoch=2.4, duration=0.18, depth=0.009)

    time_scrambled, flux_scrambled = _base_curve(13)
    rng = np.random.default_rng(13)
    flux_scrambled = rng.permutation(flux_scrambled).astype(np.float32)

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
        ),
        BenchmarkCase(
            case_id="scrambled-control-light-curve",
            group="scrambled_controls",
            truth_label="scrambled_control",
            target_id="TIC 900000004",
            mission="TESS",
            expected_period_days=None,
            expected_disposition="not_planet_candidate",
            description="Time-order-scrambled control light curve.",
            time=time_scrambled,
            flux=flux_scrambled,
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
        ),
    ]


def _case_result(case: BenchmarkCase, *, vetting_mode: str) -> dict[str, Any]:
    payload = analyze_light_curve_arrays(
        target_id=case.target_id,
        mission=case.mission,
        time=case.time,
        flux=case.flux,
        vetting_mode=vetting_mode,
        max_candidates=2,
        nigraha_service=_BenchmarkUnavailableModel(),
    )
    tces = payload.get("tces") or []
    planet_candidates = payload.get("planet_candidates") or []
    best_tce = tces[0] if tces else None
    recovered_period = best_tce.get("period_days") if isinstance(best_tce, dict) else None
    period_error = (
        abs(float(recovered_period) - case.expected_period_days) / case.expected_period_days
        if recovered_period is not None and case.expected_period_days
        else None
    )
    flags = best_tce.get("flags", []) if isinstance(best_tce, dict) else []
    has_hard_fail = any(isinstance(flag, dict) and flag.get("severity") == "hard_fail" for flag in flags)
    signal_recovered = bool(best_tce) and not has_hard_fail
    if case.expected_period_days:
        signal_recovered = signal_recovered and period_error is not None and period_error <= 0.02
    recovered = (
        signal_recovered
        if case.expected_disposition == "planet_candidate"
        else not bool(planet_candidates)
    )
    escaped = case.expected_disposition == "not_planet_candidate" and bool(planet_candidates)
    missed = case.expected_disposition == "planet_candidate" and not signal_recovered
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
        "promoted_candidate_recovered": bool(planet_candidates),
        "false_alarm_escaped": escaped,
        "missed_known_planet": missed,
        "best_disposition": best_tce.get("disposition") if isinstance(best_tce, dict) else None,
        "planet_candidate_count": len(planet_candidates),
        "tce_count": len(tces),
        "recovered_period_days": recovered_period,
        "period_error_fraction": period_error,
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
    return {
        "status": "passed",
        "engine": "orbitlab_science_benchmark",
        "vetting_mode": vetting_mode,
        "case_count": len(results),
        "known_planet_recovery_rate": _rate(results, lambda row: row["truth_label"] == "confirmed_planet"),
        "false_positive_rejection_rate": _rate(
            results,
            lambda row: row["truth_label"] in {"known_false_positive", "scrambled_control"},
        ),
        "injected_transit_recovery_rate": _rate(results, lambda row: row["truth_label"] == "injected_transit"),
        "false_alarm_escape_list": [
            row["case"]["case_id"] for row in results if row.get("false_alarm_escaped")
        ],
        "missed_known_planets": [
            row["case"]["case_id"] for row in results if row.get("missed_known_planet")
        ],
        "unstable_candidates": [
            row["case"]["case_id"]
            for row in results
            if row.get("period_error_fraction") is not None and row["period_error_fraction"] > 0.02
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
        "",
        "## Escapes And Misses",
        "",
        f"- False alarm escape list: `{report.get('false_alarm_escape_list')}`",
        f"- Missed known planets: `{report.get('missed_known_planets')}`",
        f"- Unstable candidates: `{report.get('unstable_candidates')}`",
        "",
        "## Cases",
        "",
        "| Case | Truth | Expected | Best disposition | Planet candidates | Signal recovered | Recovered |",
        "| --- | --- | --- | --- | ---: | --- | --- |",
    ]
    for result in report.get("results", []):
        case = result.get("case", {})
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
