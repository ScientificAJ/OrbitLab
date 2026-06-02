from __future__ import annotations

import importlib.util
from pathlib import Path


def _release_room_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "build_release_room.py"
    spec = importlib.util.spec_from_file_location("build_release_room", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_benchmark_delta_reports_metric_changes_without_hiding_science_lists(tmp_path):
    module = _release_room_module()
    previous = {
        "known_planet_recovery_rate": 0.5,
        "false_positive_rejection_rate": 1.0,
        "injected_transit_recovery_rate": 0.0,
        "case_count": 4,
        "false_alarm_escape_list": ["old-fp"],
        "missed_known_planets": ["old-miss"],
        "unstable_candidates": [],
    }
    current = {
        "known_planet_recovery_rate": 1.0,
        "false_positive_rejection_rate": 0.75,
        "injected_transit_recovery_rate": 1.0,
        "case_count": 5,
        "false_alarm_escape_list": [],
        "missed_known_planets": [],
        "unstable_candidates": ["unstable-case"],
    }
    previous_path = tmp_path / "benchmark_report.json"
    previous_path.write_text(module.json.dumps(previous), encoding="utf-8")

    delta = module._benchmark_delta(previous_path, current)

    assert delta["status"] == "ready"
    assert delta["metrics"]["known_planet_recovery_rate"]["delta"] == 0.5
    assert delta["metrics"]["false_positive_rejection_rate"]["delta"] == -0.25
    assert delta["false_alarm_escape_list"]["previous"] == ["old-fp"]
    assert delta["false_alarm_escape_list"]["current"] == []
    assert delta["unstable_candidates"]["current"] == ["unstable-case"]


def test_benchmark_delta_marks_missing_baseline_explicitly():
    module = _release_room_module()

    delta = module._benchmark_delta(None, {"case_count": 5})

    assert delta["status"] == "baseline_unavailable"
    assert delta["metrics"]["case_count"]["previous"] is None
    assert delta["metrics"]["case_count"]["current"] == 5


def test_dependency_name_parses_python_requirement_names_without_config_noise():
    module = _release_room_module()

    assert module._dependency_name("uvicorn[standard]>=0.30") == "uvicorn"
    assert module._dependency_name("batman-package>=2.4") == "batman-package"
    assert module._dependency_name("pytest-cov>=5.0") == "pytest-cov"
    assert module._dependency_name('"not a requirement"') == ""
