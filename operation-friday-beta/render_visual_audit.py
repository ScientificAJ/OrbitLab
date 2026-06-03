#!/usr/bin/env python3
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent
REPORTS_DIR = ROOT / "reports"
VISUAL_DIR = REPORTS_DIR / "visual-audit"


def _load_workflows() -> list[tuple[str, dict[str, Any]]]:
    workflows = []
    for path in sorted(REPORTS_DIR.glob("*/workflow.json")):
        workflows.append((path.parent.name, json.loads(path.read_text(encoding="utf-8"))))
    return workflows


def _as_array(values: Any) -> np.ndarray:
    return np.asarray(values if values is not None else [], dtype=float)


def _candidate_list(result: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("tces", "planet_candidates", "candidates"):
        value = result.get(key)
        if isinstance(value, list):
            return value
    return []


def _finite_ylim(values: np.ndarray, pad: float = 0.08) -> tuple[float, float] | None:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None
    low = float(np.nanpercentile(finite, 1))
    high = float(np.nanpercentile(finite, 99))
    if math.isclose(low, high):
        return low - 1.0, high + 1.0
    span = high - low
    return low - span * pad, high + span * pad


def _format_number(value: Any, *, digits: int = 4) -> str:
    if not isinstance(value, int | float) or not math.isfinite(float(value)):
        return "n/a"
    return f"{float(value):.{digits}g}"


def _plot_tpf(ax, workflow: dict[str, Any]) -> None:
    preview = workflow.get("tpf_preview", {}).get("payload") or {}
    image = _as_array(preview.get("image"))
    mask = np.asarray((workflow.get("aperture_mask", {}).get("payload") or {}).get("mask") or [], dtype=bool)
    ax.set_title("TPF preview + aperture")
    if image.size == 0:
        ax.text(0.5, 0.5, "No image", ha="center", va="center")
        return
    finite = image[np.isfinite(image)]
    vmin = float(np.nanpercentile(finite, 5)) if finite.size else None
    vmax = float(np.nanpercentile(finite, 99)) if finite.size else None
    ax.imshow(image, origin="lower", cmap="magma", vmin=vmin, vmax=vmax)
    if mask.shape == image.shape:
        y, x = np.where(mask)
        ax.scatter(x, y, s=120, facecolors="none", edgecolors="#45f0ff", linewidths=1.4)
    ax.set_xticks([])
    ax.set_yticks([])


def _plot_periodogram(ax, result: dict[str, Any], candidates: list[dict[str, Any]]) -> None:
    periodogram = result.get("periodogram") or {}
    period = _as_array(periodogram.get("period"))
    power = _as_array(periodogram.get("power"))
    ax.set_title("Periodogram")
    if period.size == 0 or power.size == 0:
        ax.text(0.5, 0.5, "No periodogram", ha="center", va="center")
        return
    size = min(period.size, power.size)
    period = period[:size]
    power = power[:size]
    ax.plot(period, power, color="#23395b", linewidth=0.8)
    colors = ["#d33f49", "#167a5b", "#7a4cc2", "#da8a00"]
    for index, candidate in enumerate(candidates):
        candidate_period = candidate.get("period_days", candidate.get("period"))
        if isinstance(candidate_period, int | float) and math.isfinite(float(candidate_period)):
            ax.axvline(float(candidate_period), color=colors[index % len(colors)], linewidth=1.0, alpha=0.85)
    ax.set_xlabel("period days")
    ax.set_ylabel("power")
    ylim = _finite_ylim(power)
    if ylim:
        ax.set_ylim(*ylim)


def _plot_folded_curves(fig, grid, result: dict[str, Any], candidates: list[dict[str, Any]]) -> None:
    folded = result.get("folded_curves") or {}
    for index in range(4):
        ax = fig.add_subplot(grid[1 + index // 2, index % 2])
        if index >= len(candidates):
            ax.axis("off")
            continue
        candidate = candidates[index]
        candidate_id = candidate.get("candidate_id") or candidate.get("tce_id")
        curve = folded.get(candidate_id) or {}
        phase = _as_array(curve.get("phase"))
        flux = _as_array(curve.get("flux"))
        depth_ppm = candidate.get("depth_ppm")
        depth_source = (candidate.get("detection_metrics") or {}).get("depth_source") or candidate.get("depth_source")
        title = (
            f"{candidate_id}\n"
            f"P={_format_number(candidate.get('period_days', candidate.get('period')), digits=6)} d, "
            f"SNR={_format_number(candidate.get('signal_to_noise'))}, "
            f"depth={_format_number(depth_ppm)} ppm, "
            f"{candidate.get('disposition')} / "
            f"{(candidate.get('science_readiness') or {}).get('status')}\n"
            f"depth source: {depth_source or 'unknown'}"
        )
        ax.set_title(title, fontsize=9)
        if phase.size == 0 or flux.size == 0:
            ax.text(0.5, 0.5, "No folded curve", ha="center", va="center")
            continue
        size = min(phase.size, flux.size)
        phase = phase[:size]
        flux = flux[:size]
        ax.scatter(phase, flux, s=8, color="#203354", alpha=0.75)
        ax.axvline(0.0, color="#d33f49", linewidth=0.8, alpha=0.7)
        ax.set_xlabel("phase")
        ax.set_ylabel("flux")
        ylim = _finite_ylim(flux)
        if ylim:
            ax.set_ylim(*ylim)


def render_case(case_id: str, workflow: dict[str, Any]) -> Path:
    result = workflow.get("analysis_result", {}).get("payload") or {}
    candidates = _candidate_list(result)
    fig = plt.figure(figsize=(13.5, 10.5), constrained_layout=True)
    grid = fig.add_gridspec(3, 2)
    case = workflow.get("case") or {}
    fig.suptitle(
        f"{case_id}: {case.get('query')} / {case.get('mission')} | "
        f"target {workflow.get('selected_target')} | audit {workflow.get('audit_status')}",
        fontsize=14,
    )
    _plot_tpf(fig.add_subplot(grid[0, 0]), workflow)
    _plot_periodogram(fig.add_subplot(grid[0, 1]), result, candidates)
    _plot_folded_curves(fig, grid, result, candidates)
    VISUAL_DIR.mkdir(parents=True, exist_ok=True)
    path = VISUAL_DIR / f"{case_id}.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def main() -> int:
    paths = [render_case(case_id, workflow) for case_id, workflow in _load_workflows()]
    index = [
        "# Operation Friday Beta Visual Audit Boards",
        "",
        "These boards render the saved real API workflow payloads into inspectable",
        "science visuals: TPF aperture, periodogram, folded curves, candidate metrics,",
        "and depth provenance.",
        "",
        "- `manual-visual-review.md`",
    ]
    index.extend(f"- `{path.relative_to(ROOT)}`" for path in paths)
    (VISUAL_DIR / "README.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    print(json.dumps([str(path) for path in paths], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
