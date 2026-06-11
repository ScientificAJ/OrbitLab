"""Per-population SDE calibration: lookup semantics and pipeline wiring.

The contract under test: calibration may only RAISE the bar above the
published floor, missing tables/bins degrade to the floor with explicit
provenance (never an exception), and the paper gate consumes the calibrated
threshold with full provenance in its thresholds payload.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from orbitlab.science.bls import TransitCandidate
from orbitlab.science.pipeline import _apply_paper_grade_vetting
from orbitlab.science.science_config import load_science_config
from orbitlab.science.sde_calibration import (
    calibrated_sde_threshold,
    classify_population,
    clear_table_cache,
)

CONFIG = load_science_config()


def _write_table(path: Path, bin_id: str, threshold: float) -> Path:
    path.write_text(
        "\n".join(
            [
                'schema_version = "orbitlab.sde_calibration.v1"',
                "[metadata]",
                "fap_target = 0.001",
                f"[bins.{bin_id}]",
                f"sde_threshold = {threshold}",
                "n_null = 200",
            ]
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_table_cache()
    yield
    clear_table_cache()


def test_classify_population_bucket_edges():
    base = dict(mission="TESS", baseline_days=27.0, red_noise_beta=1.0)
    assert classify_population(cadence_seconds=299.0, **base) == "tess_short_cadence_short_baseline_quiet"
    assert classify_population(cadence_seconds=301.0, **base) == "tess_long_cadence_short_baseline_quiet"
    assert (
        classify_population(mission="TESS", cadence_seconds=120.0, baseline_days=27.0, red_noise_beta=1.31)
        == "tess_short_cadence_short_baseline_red"
    )
    # Kepler baselines bucket at 90 d, not 35 d.
    assert (
        classify_population(mission="Kepler", cadence_seconds=1800.0, baseline_days=80.0, red_noise_beta=1.0)
        == "kepler_long_cadence_short_baseline_quiet"
    )
    assert (
        classify_population(mission="TESS", cadence_seconds=None, baseline_days=None, red_noise_beta=None)
        == "tess_unknown_cadence_unknown_baseline_unknown_beta"
    )


def test_missing_table_and_missing_bin_fall_back_to_floor(tmp_path):
    result = calibrated_sde_threshold(
        mission="TESS",
        cadence_seconds=120.0,
        baseline_days=27.0,
        red_noise_beta=1.0,
        config=CONFIG,
        table_path=tmp_path / "absent.toml",
    )
    assert result["threshold"] == CONFIG.paper_tls_sde_min
    assert result["source"] == "uncalibrated_floor"

    table = _write_table(tmp_path / "other_bin.toml", "tess_long_cadence_short_baseline_red", 9.5)
    result = calibrated_sde_threshold(
        mission="TESS",
        cadence_seconds=120.0,
        baseline_days=27.0,
        red_noise_beta=1.0,
        config=CONFIG,
        table_path=table,
    )
    assert result["source"] == "uncalibrated_floor"


def test_calibrated_value_used_but_floored(tmp_path):
    bin_id = "tess_short_cadence_short_baseline_quiet"
    above = _write_table(tmp_path / "above.toml", bin_id, 9.2)
    result = calibrated_sde_threshold(
        mission="TESS",
        cadence_seconds=120.0,
        baseline_days=27.0,
        red_noise_beta=1.0,
        config=CONFIG,
        table_path=above,
    )
    assert result["threshold"] == 9.2
    assert result["source"] == "calibrated"

    clear_table_cache()
    below = _write_table(tmp_path / "below.toml", bin_id, 3.0)
    result = calibrated_sde_threshold(
        mission="TESS",
        cadence_seconds=120.0,
        baseline_days=27.0,
        red_noise_beta=1.0,
        config=CONFIG,
        table_path=below,
    )
    # The published floor wins: calibration may never weaken the gate.
    assert result["threshold"] == CONFIG.paper_tls_sde_min
    assert result["source"] == "calibrated"


def test_paper_gate_consumes_calibrated_threshold(monkeypatch, tmp_path):
    import orbitlab.science.sde_calibration as sde_mod

    bin_id = "tess_short_cadence_short_baseline_quiet"
    table = _write_table(tmp_path / "table.toml", bin_id, 9.0)
    monkeypatch.setattr(sde_mod, "TABLE_PATH", table)
    # pipeline imported the function by name; patch its default through the
    # module the pipeline calls into.
    import orbitlab.science.pipeline as pipeline_mod

    monkeypatch.setattr(
        pipeline_mod,
        "calibrated_sde_threshold",
        lambda **kw: sde_mod.calibrated_sde_threshold(**{**kw, "table_path": table}),
    )

    candidate = TransitCandidate(3.0, 0.4, 0.1, 0.004, 12.0, 30.0)
    support = {
        "effective_snr": 30.0,
        "observed_transit_count": 8,
        "cadence_seconds": 120.0,
        "baseline_days": 27.0,
        "red_noise_beta": 1.0,
    }

    def gate(sde_value):
        flags: list[dict] = []
        paper = _apply_paper_grade_vetting(
            flags=flags,
            candidate=candidate,
            config=CONFIG,
            support=support,
            tls={"status": "complete", "sde": sde_value, "distinct_transit_count": 8},
            model_shift={"status": "pass", "hard_fail": False},
            sweet={"status": "pass"},
            ml={"probability": 0.9},
            catalog_context={},
            fpp={"status": "complete", "fpp": 0.001, "nfpp": 0.0001},
            mission_upper="TESS",
        )
        return paper, {flag["code"] for flag in flags}

    paper, codes = gate(8.0)  # above the 7.0 floor, below the 9.0 calibrated bar
    assert "paper_tls_sde" in codes
    assert paper["thresholds"]["tls_sde_threshold_used"] == 9.0
    assert paper["thresholds"]["sde_population_bin"] == bin_id
    assert paper["thresholds"]["sde_threshold_source"] == "calibrated"
    assert paper["thresholds"]["tls_sde_min"] == CONFIG.paper_tls_sde_min

    paper, codes = gate(9.5)
    assert "paper_tls_sde" not in codes
