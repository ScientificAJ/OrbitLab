from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path
from typing import Any


def _json_text(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _series_csv(*, headers: tuple[str, ...], rows: list[tuple[Any, ...]]) -> str:
    handle = StringIO()
    writer = csv.writer(handle)
    writer.writerow(headers)
    writer.writerows(rows)
    return handle.getvalue()


def _xy_csv(x_name: str, y_name: str, x_values: list[Any], y_values: list[Any]) -> str:
    rows = list(zip(x_values or [], y_values or [], strict=False))
    return _series_csv(headers=(x_name, y_name), rows=rows)


def _candidate_markdown(tce: dict[str, Any]) -> str:
    flags = tce.get("flags") if isinstance(tce.get("flags"), list) else []
    flag_lines = [
        f"- `{flag.get('severity', 'info')}` `{flag.get('code', 'unknown')}`: {flag.get('message', '')}"
        for flag in flags
        if isinstance(flag, dict)
    ]
    if not flag_lines:
        flag_lines = ["- none"]
    return (
        f"# OrbitLab TCE Evidence\n\n"
        f"- TCE ID: `{tce.get('tce_id') or tce.get('candidate_id')}`\n"
        f"- Disposition: `{tce.get('disposition')}`\n"
        f"- Action: `{tce.get('action_label')}`\n"
        f"- Period days: `{tce.get('period_days') or tce.get('period')}`\n"
        f"- Epoch days: `{tce.get('epoch_days') or tce.get('epoch')}`\n"
        f"- Duration days: `{tce.get('duration_days') or tce.get('duration')}`\n"
        f"- Depth ppm: `{tce.get('depth_ppm')}`\n"
        f"- Effective SNR: `{(tce.get('detection_metrics') or {}).get('effective_snr')}`\n\n"
        f"## Flags\n\n"
        + "\n".join(flag_lines)
        + "\n"
    )


def build_evidence_packet_files(payload: dict[str, Any]) -> dict[str, str]:
    result_id = str(payload.get("result_id") or "result")
    tces = payload.get("tces") if isinstance(payload.get("tces"), list) else []
    files: dict[str, str] = {
        "manifest.json": _json_text(
            {
                "result_id": result_id,
                "target_id": payload.get("target_id"),
                "mission": payload.get("mission"),
                "schema_version": payload.get("schema_version"),
                "pipeline_version": payload.get("pipeline_version"),
                "science_config_hash": payload.get("science_config_hash"),
                "vetting_mode": payload.get("vetting_mode"),
                "tce_count": len(tces),
                "planet_candidate_count": len(payload.get("planet_candidates") or []),
                "engine_status": payload.get("engine_status"),
            }
        ),
        "data_quality.json": _json_text(payload.get("data_quality") or {}),
    }

    light_curve = payload.get("light_curve") if isinstance(payload.get("light_curve"), dict) else {}
    files["light_curve.csv"] = _xy_csv(
        "time_days",
        "flux",
        light_curve.get("time") or [],
        light_curve.get("flux") or [],
    )

    periodogram = payload.get("periodogram") if isinstance(payload.get("periodogram"), dict) else {}
    files["periodogram.csv"] = _series_csv(
        headers=("period_days", "power", "duration_days"),
        rows=list(
            zip(
                periodogram.get("period") or [],
                periodogram.get("power") or [],
                periodogram.get("duration") or [],
                strict=False,
            )
        ),
    )

    folded = payload.get("folded_curves") if isinstance(payload.get("folded_curves"), dict) else {}
    for index, tce in enumerate(tces, start=1):
        if not isinstance(tce, dict):
            continue
        tce_id = str(tce.get("tce_id") or tce.get("candidate_id") or f"tce-{index}")
        prefix = f"tces/{tce_id}"
        curve = folded.get(tce_id) if isinstance(folded.get(tce_id), dict) else {}
        files[f"{prefix}/folded_curve.csv"] = _xy_csv(
            "phase",
            "flux",
            curve.get("phase") or [],
            curve.get("flux") or [],
        )
        files[f"{prefix}/vetting.json"] = _json_text(tce.get("vetting") or {})
        files[f"{prefix}/catalog_context.json"] = _json_text(tce.get("catalog_context") or {})
        files[f"{prefix}/triceratops.json"] = _json_text(tce.get("fpp") or {})
        files[f"{prefix}/ml_evidence.json"] = _json_text(tce.get("ml") or {})
        files[f"{prefix}/detection_metrics.json"] = _json_text(tce.get("detection_metrics") or {})
        files[f"{prefix}/final_disposition.md"] = _candidate_markdown(tce)
    return files


def write_evidence_packet(payload: dict[str, Any], output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    files = build_evidence_packet_files(payload)
    for relative_path, content in files.items():
        destination = root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    return {
        "status": "passed",
        "engine": "orbitlab_evidence_packet",
        "output_dir": str(root),
        "file_count": len(files),
        "files": sorted(files),
    }
