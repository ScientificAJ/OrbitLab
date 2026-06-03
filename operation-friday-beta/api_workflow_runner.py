#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
TARGETS_PATH = ROOT / "targets.json"
REPORTS_DIR = ROOT / "reports"
RAW_DIRNAME = "raw"


@dataclass(frozen=True)
class ApiResponse:
    status: int
    payload: Any
    elapsed_s: float


class ApiClient:
    def __init__(self, base_url: str, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> ApiResponse:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                parsed = json.loads(raw) if raw else None
                return ApiResponse(status=response.status, payload=parsed, elapsed_s=time.perf_counter() - started)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw) if raw else {"detail": exc.reason}
            except json.JSONDecodeError:
                parsed = {"detail": raw or exc.reason}
            return ApiResponse(status=exc.code, payload=parsed, elapsed_s=time.perf_counter() - started)

    def get(self, path: str, params: dict[str, Any] | None = None) -> ApiResponse:
        if params:
            path = f"{path}?{urllib.parse.urlencode(params)}"
        return self.request("GET", path)

    def post(self, path: str, payload: dict[str, Any]) -> ApiResponse:
        return self.request("POST", path, payload)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _finite_values(grid: list[list[float]]) -> list[float]:
    return [float(value) for row in grid for value in row if isinstance(value, int | float) and math.isfinite(value)]


def _bright_aperture_mask(preview: dict[str, Any]) -> list[list[bool]]:
    image = preview.get("image") or []
    values = _finite_values(image)
    if not values:
        raise ValueError("TPF preview image has no finite values for aperture mask")
    sorted_values = sorted(values)
    threshold_index = max(0, int(len(sorted_values) * 0.85) - 1)
    threshold = sorted_values[threshold_index]
    mask = [[float(value) >= threshold for value in row] for row in image]
    if not any(pixel for row in mask for pixel in row):
        height = len(image)
        width = len(image[0]) if height else 0
        if height == 0 or width == 0:
            raise ValueError("TPF preview image is empty")
        mask[height // 2][width // 2] = True
    return mask


def _save_step(case_dir: Path, step: str, response: ApiResponse) -> dict[str, Any]:
    step_payload = {
        "step": step,
        "status": response.status,
        "elapsed_s": round(response.elapsed_s, 3),
        "payload": response.payload,
    }
    _write_json(case_dir / RAW_DIRNAME / f"{step}.json", step_payload)
    return step_payload


def _is_ok(response: ApiResponse) -> bool:
    return 200 <= response.status < 300


def _first_product(products: list[dict[str, Any]], mission: str) -> dict[str, Any] | None:
    mission_upper = mission.upper()
    matching = [item for item in products if str(item.get("mission", "")).upper().startswith(mission_upper)]
    candidates = matching or products
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda item: (
            1 if "_fast-" in str(item.get("product_uri", "")) or "a_fast" in str(item.get("product_uri", "")) else 0,
            int(item.get("size") or 10**18),
            str(item.get("product_id", "")),
            str(item.get("product_uri", "")),
        ),
    )[0]


def _result_candidates(result: dict[str, Any]) -> list[dict[str, Any]]:
    tces = result.get("tces")
    if isinstance(tces, list):
        return tces
    candidates = result.get("planet_candidates") or result.get("candidates") or []
    return candidates if isinstance(candidates, list) else []


def _folded_curve_health(folded_curves: dict[str, Any], candidates: list[dict[str, Any]]) -> list[str]:
    findings: list[str] = []
    for candidate in candidates:
        candidate_id = candidate.get("candidate_id") or candidate.get("tce_id")
        if not candidate_id:
            findings.append("candidate_without_id: result candidate/TCE has no candidate_id or tce_id")
            continue
        curve = folded_curves.get(candidate_id)
        if not curve:
            findings.append(f"{candidate_id}: missing folded curve")
            continue
        phase = curve.get("phase") or []
        flux = curve.get("flux") or []
        if len(phase) != len(flux):
            findings.append(f"{candidate_id}: folded curve phase/flux length mismatch")
        if len(phase) < 20:
            findings.append(f"{candidate_id}: folded curve has too few points ({len(phase)})")
        finite_flux = [value for value in flux if isinstance(value, int | float) and math.isfinite(value)]
        if len(finite_flux) < max(10, len(flux) // 2):
            findings.append(f"{candidate_id}: folded curve has excessive non-finite flux values")
    return findings


def _periodogram_health(periodogram: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    period = periodogram.get("period") or []
    power = periodogram.get("power") or []
    duration = periodogram.get("duration") or []
    if not period or not power:
        findings.append("periodogram_missing: period or power array is empty")
    if len(period) != len(power):
        findings.append(f"periodogram_length_mismatch: period={len(period)} power={len(power)}")
    if duration and len(duration) not in {1, len(period)}:
        findings.append(f"periodogram_duration_shape_suspicious: duration={len(duration)} period={len(period)}")
    finite_period = [value for value in period if isinstance(value, int | float) and math.isfinite(value)]
    if len(finite_period) != len(period):
        findings.append("periodogram_nonfinite_period_values")
    if finite_period and any(value <= 0 for value in finite_period):
        findings.append("periodogram_nonpositive_period_values")
    return findings


def _candidate_health(candidates: list[dict[str, Any]], result_kind: str) -> list[str]:
    findings: list[str] = []
    seen_ids: set[str] = set()
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or candidate.get("tce_id") or "")
        if not candidate_id:
            findings.append(f"{result_kind}: candidate missing id")
        elif candidate_id in seen_ids:
            findings.append(f"{result_kind}: duplicate candidate id {candidate_id}")
        seen_ids.add(candidate_id)
        period = candidate.get("period_days", candidate.get("period"))
        duration = candidate.get("duration_days", candidate.get("duration"))
        depth = candidate.get("depth_fraction", candidate.get("depth"))
        snr = candidate.get("signal_to_noise")
        disposition = candidate.get("disposition")
        if not isinstance(period, int | float) or not math.isfinite(float(period)) or float(period) <= 0:
            findings.append(f"{candidate_id}: invalid period {period}")
        if not isinstance(duration, int | float) or not math.isfinite(float(duration)) or float(duration) <= 0:
            findings.append(f"{candidate_id}: invalid duration {duration}")
        elif isinstance(period, int | float) and math.isfinite(float(period)) and float(duration) >= float(period):
            findings.append(f"{candidate_id}: duration >= period")
        if not isinstance(depth, int | float) or not math.isfinite(float(depth)) or float(depth) <= 0:
            findings.append(f"{candidate_id}: invalid depth {depth}")
        depth_source = candidate.get("depth_source") or (candidate.get("detection_metrics") or {}).get("depth_source")
        if result_kind == "analysis" and not depth_source:
            findings.append(f"{candidate_id}: missing depth_source provenance")
        if not isinstance(snr, int | float) or not math.isfinite(float(snr)):
            findings.append(f"{candidate_id}: invalid signal_to_noise {snr}")
        if disposition == "planet_candidate" and isinstance(snr, int | float) and float(snr) < 6:
            findings.append(f"{candidate_id}: promoted planet_candidate has low SNR {snr}")
        readiness = candidate.get("science_readiness") if isinstance(candidate.get("science_readiness"), dict) else {}
        action_label = candidate.get("action_label")
        if (
            candidate.get("catalog_match")
            and disposition == "planet_candidate"
            and action_label != "follow_up_needed"
            and readiness.get("status") not in {"blocked", "review"}
        ):
            findings.append(
                f"{candidate_id}: catalog-matched signal promoted; "
                "verify wording remains follow-up candidate, not confirmation"
            )
    return findings


def _format_float(value: Any, digits: int = 4) -> str:
    if isinstance(value, int | float) and math.isfinite(float(value)):
        return f"{float(value):.{digits}g}"
    return "-"


def _format_depth_ppm(candidate: dict[str, Any]) -> str:
    depth = candidate.get("depth_ppm")
    if depth is None and isinstance(candidate.get("depth"), int | float):
        depth = float(candidate["depth"]) * 1_000_000.0
    return _format_float(depth, 5)


def _step_rows(workflow: dict[str, Any]) -> list[str]:
    rows = [
        "| Step | HTTP | Elapsed s |",
        "| --- | ---: | ---: |",
    ]
    ordered_steps = [
        "health",
        "models",
        "search",
        "products",
        "tpf_preview",
        "aperture_mask",
        "bls_preview",
        "analysis_job_create",
        "analysis_result",
        "report",
        "save_session",
        "sessions",
    ]
    for step in ordered_steps:
        item = workflow.get(step)
        if not isinstance(item, dict):
            rows.append(f"| `{step}` | - | - |")
            continue
        rows.append(f"| `{step}` | {item.get('status', '-')} | {_format_float(item.get('elapsed_s'), 3)} |")
    poll = workflow.get("analysis_job_poll")
    if isinstance(poll, dict):
        attempts = poll.get("attempts") or []
        final = poll.get("final") or {}
        payload = final.get("payload") if isinstance(final, dict) else {}
        rows.append(
            "| `analysis_job_poll` | "
            f"{final.get('status', '-')} | "
            f"{len(attempts)} polls, status `{(payload or {}).get('status', '-')}` |"
        )
    return rows


def _candidate_rows(candidates: list[dict[str, Any]]) -> list[str]:
    rows = [
        (
            "| ID | Period d | Duration h | Depth ppm | Depth source | SNR | Disposition | "
            "Action | Readiness | ML | Catalog |"
        ),
        "| --- | ---: | ---: | ---: | --- | ---: | --- | --- | --- | --- | --- |",
    ]
    if not candidates:
        rows.append("| - | - | - | - | - | - | - | - | - | - | - |")
        return rows
    for candidate in candidates:
        candidate_id = candidate.get("candidate_id") or candidate.get("tce_id") or "-"
        duration_hours = candidate.get("duration_hours")
        if duration_hours is None and isinstance(candidate.get("duration_days"), int | float):
            duration_hours = float(candidate["duration_days"]) * 24.0
        ml = candidate.get("ml") if isinstance(candidate.get("ml"), dict) else {}
        ml_label = ml.get("label") or ml.get("status") or _format_float(ml.get("probability"), 3)
        catalog = candidate.get("catalog_match")
        catalog_label = "-"
        if isinstance(catalog, dict):
            catalog_label = str(catalog.get("planet") or catalog.get("target") or "matched")
        readiness = candidate.get("science_readiness") if isinstance(candidate.get("science_readiness"), dict) else {}
        depth_source = candidate.get("depth_source") or (candidate.get("detection_metrics") or {}).get("depth_source")
        rows.append(
            "| "
            + " | ".join(
                [
                    f"`{candidate_id}`",
                    _format_float(candidate.get("period_days", candidate.get("period")), 6),
                    _format_float(duration_hours, 4),
                    _format_depth_ppm(candidate),
                    str(depth_source or "-"),
                    _format_float(candidate.get("signal_to_noise"), 4),
                    str(candidate.get("disposition") or "-"),
                    str(candidate.get("action_label") or "-"),
                    str(readiness.get("status") or "-"),
                    str(ml_label or "-"),
                    catalog_label,
                ]
            )
            + " |"
        )
    return rows


def _quarantined_artifacts(candidates: list[dict[str, Any]]) -> list[str]:
    artifacts: list[str] = []
    for candidate in candidates:
        disposition = candidate.get("disposition")
        candidate_id = candidate.get("candidate_id") or candidate.get("tce_id") or "candidate"
        depth = candidate.get("depth_fraction", candidate.get("depth"))
        duration = candidate.get("duration_days", candidate.get("duration"))
        period = candidate.get("period_days", candidate.get("period"))
        reasons = []
        if isinstance(depth, int | float) and math.isfinite(float(depth)) and float(depth) >= 0.1:
            reasons.append(f"implausibly deep signal ({_format_float(float(depth) * 100.0, 4)}% depth)")
        if (
            isinstance(duration, int | float)
            and isinstance(period, int | float)
            and math.isfinite(float(duration))
            and math.isfinite(float(period))
            and float(period) > 0
            and float(duration) / float(period) >= 0.25
        ):
            reasons.append(f"large duration/period ratio ({_format_float(float(duration) / float(period), 4)})")
        if reasons and disposition != "planet_candidate":
            artifacts.append(
                f"- `{candidate_id}` is quarantined as `{disposition}`: "
                + "; ".join(reasons)
                + "."
            )
    return artifacts


def _science_snapshot(workflow: dict[str, Any]) -> list[str]:
    preview = workflow.get("bls_preview", {}).get("payload") or {}
    result = workflow.get("analysis_result", {}).get("payload") or {}
    candidates = _result_candidates(result)
    periodogram = result.get("periodogram") or {}
    preview_tces = preview.get("tces") or preview.get("candidates") or []
    aliases_match = result.get("candidates") == result.get("planet_candidates") if result else False
    return [
        f"- Preview TCEs: `{len(preview_tces)}`",
        f"- Analysis ledger entries: `{len(candidates)}`",
        "- Periodogram samples: "
        f"`{len(periodogram.get('period') or [])}` periods, `{len(periodogram.get('power') or [])}` powers",
        f"- Folded curves: `{len(result.get('folded_curves') or {})}`",
        f"- `candidates` / `planet_candidates` alias match: `{aliases_match}`",
    ]


def _ml_health(result: dict[str, Any], candidates: list[dict[str, Any]], models: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    mission = str(result.get("mission", "")).upper()
    model_key = {"TESS": "nigraha_tess", "KEPLER": "kepler_astronet", "K2": "k2_exomac_kkt"}.get(mission)
    if model_key and (models.get(model_key) or {}).get("status") == "ready":
        for candidate in candidates:
            candidate_id = candidate.get("candidate_id") or candidate.get("tce_id")
            ml = candidate.get("ml")
            if not ml:
                findings.append(f"{candidate_id}: model {model_key} ready but candidate has no ML result")
                continue
            probability = ml.get("probability")
            if probability is not None and not (isinstance(probability, int | float) and 0 <= float(probability) <= 1):
                findings.append(f"{candidate_id}: ML probability out of range {probability}")
            if not ml.get("model_source"):
                findings.append(f"{candidate_id}: ML result missing model_source")
    return findings


def audit_result(case: dict[str, Any], workflow: dict[str, Any]) -> tuple[str, list[str]]:
    findings: list[str] = []
    preview = workflow.get("bls_preview", {}).get("payload") or {}
    result = workflow.get("analysis_result", {}).get("payload") or {}
    models = workflow.get("models", {}).get("payload") or {}
    final_job = (workflow.get("analysis_job_poll") or {}).get("final", {}).get("payload") or {}
    if not workflow.get("selected_target"):
        findings.append("No target selected from search results")
    if not workflow.get("selected_product"):
        findings.append("No product selected from product list")
    if preview:
        findings.extend(_periodogram_health(preview.get("periodogram") or {}))
        findings.extend(_candidate_health(preview.get("tces") or preview.get("candidates") or [], "preview"))
        findings.extend(_folded_curve_health(preview.get("folded_curves") or {}, preview.get("tces") or []))
    else:
        findings.append("BLS preview payload missing")
    if result:
        candidates = _result_candidates(result)
        findings.extend(_periodogram_health(result.get("periodogram") or {}))
        findings.extend(_candidate_health(candidates, "analysis"))
        findings.extend(_folded_curve_health(result.get("folded_curves") or {}, candidates))
        findings.extend(_ml_health(result, candidates, models))
        if result.get("candidates") != result.get("planet_candidates"):
            findings.append("candidates and planet_candidates aliases differ in analysis response")
        for candidate in candidates:
            disposition = candidate.get("disposition")
            if disposition == "planet_candidate" and not candidate.get("science_readiness"):
                findings.append(f"{candidate.get('candidate_id')}: promoted candidate missing science_readiness")
    else:
        findings.append("Full analysis result missing")
        if final_job.get("status") == "failed" and final_job.get("error"):
            findings.append(f"Analysis job failed: {final_job['error']}")
    if not _is_step_ok(workflow, "report"):
        findings.append("Report export step failed or missing")
    if not _is_step_ok(workflow, "save_session"):
        findings.append("Save session step failed or missing")
    status = "pass" if not findings else "review_needed"
    lines = [
        f"# Operation Friday Beta Audit: {case['case_id']}",
        "",
        f"- Query: `{case['query']}`",
        f"- Mission: `{case['mission']}`",
        f"- Purpose: {case['purpose']}",
        f"- Status: `{status}`",
        "",
        "## Selected Target/Product",
        "",
        f"- Target: `{workflow.get('selected_target')}`",
        f"- Product ID: `{(workflow.get('selected_product') or {}).get('product_id')}`",
        f"- Product URI: `{(workflow.get('selected_product') or {}).get('product_uri')}`",
        "",
        "## API Flow Evidence",
        "",
        *_step_rows(workflow),
        "",
        "## Science Snapshot",
        "",
        *_science_snapshot(workflow),
        "",
        "## Analysis Candidate Ledger",
        "",
        *_candidate_rows(_result_candidates(result)),
        "",
        "## Quarantined Artifacts",
        "",
    ]
    artifacts = _quarantined_artifacts(_result_candidates(result))
    if artifacts:
        lines.extend(artifacts)
    else:
        lines.append("- No physically suspicious rejected artifacts were found by the report heuristics.")
    lines.extend(
        [
            "",
            "## Findings",
            "",
        ]
    )
    if findings:
        lines.extend(f"- {finding}" for finding in findings)
    else:
        lines.append("- No automated scientific/API consistency findings.")
    return "\n".join(lines) + "\n", findings


def _is_step_ok(workflow: dict[str, Any], step: str) -> bool:
    item = workflow.get(step)
    return isinstance(item, dict) and 200 <= int(item.get("status", 0)) < 300


def poll_job(client: ApiClient, case_dir: Path, job_id: str, timeout_s: float, interval_s: float) -> dict[str, Any]:
    started = time.perf_counter()
    attempts = []
    while time.perf_counter() - started < timeout_s:
        response = client.get(f"/analysis-jobs/{urllib.parse.quote(job_id)}")
        step = _save_step(case_dir, f"analysis_job_poll_{len(attempts) + 1:03d}", response)
        attempts.append(step)
        payload = response.payload if isinstance(response.payload, dict) else {}
        if payload.get("status") in {"complete", "failed"}:
            return {"final": step, "attempts": attempts}
        time.sleep(interval_s)
    return {"final": {"status": 408, "payload": {"detail": "analysis polling timed out"}}, "attempts": attempts}


def run_case(client: ApiClient, case: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    case_dir = REPORTS_DIR / case["case_id"]
    if case_dir.exists():
        shutil.rmtree(case_dir)
    case_dir.mkdir(parents=True, exist_ok=True)
    workflow: dict[str, Any] = {"case": case}

    health = client.get("/health")
    workflow["health"] = _save_step(case_dir, "health", health)
    models = client.get("/models")
    workflow["models"] = _save_step(case_dir, "models", models)

    search = client.get("/search", {"query": case["query"], "mission": case["mission"]})
    workflow["search"] = _save_step(case_dir, "search", search)
    search_payload = search.payload if isinstance(search.payload, list) else []
    if not search_payload:
        workflow["error"] = "search returned no targets"
        return workflow
    selected_target = search_payload[0]
    target_id = selected_target["target_id"]
    workflow["selected_target"] = target_id

    products = client.get(f"/targets/{urllib.parse.quote(target_id, safe='')}/products", {"mission": case["mission"]})
    workflow["products"] = _save_step(case_dir, "products", products)
    products_payload = products.payload if isinstance(products.payload, list) else []
    selected_product = _first_product(products_payload, case["mission"])
    if not selected_product:
        workflow["error"] = "products returned no target pixel products"
        return workflow
    workflow["selected_product"] = selected_product
    product_uri = selected_product["product_uri"]

    preview = client.get("/tpf-preview", {"product_uri": product_uri})
    workflow["tpf_preview"] = _save_step(case_dir, "tpf_preview", preview)
    aperture_mask_id = None
    if _is_ok(preview) and isinstance(preview.payload, dict):
        mask = _bright_aperture_mask(preview.payload)
        aperture_payload = {
            "target_id": target_id,
            "product_uri": product_uri,
            "mask": mask,
            "reason": "Operation Friday Beta API-selected bright-pixel aperture mask.",
        }
        aperture = client.post("/aperture-masks", aperture_payload)
        workflow["aperture_mask"] = _save_step(case_dir, "aperture_mask", aperture)
        if _is_ok(aperture) and isinstance(aperture.payload, dict):
            aperture_mask_id = aperture.payload.get("aperture_mask_id")

    bls_payload = {
        "target_id": target_id,
        "mission": case["mission"],
        "product_uri": product_uri,
        "aperture_mask_id": aperture_mask_id,
        "min_period": 0.5,
        "max_period": 30.0,
        "max_candidates": 4,
    }
    bls = client.post("/bls-preview", bls_payload)
    workflow["bls_preview"] = _save_step(case_dir, "bls_preview", bls)

    analysis_payload = {
        "target_id": target_id,
        "mission": case["mission"],
        "product_uri": product_uri,
        "aperture_mask_id": aperture_mask_id,
        "max_candidates": 4,
        "vetting_mode": "paper",
    }
    analysis_job = client.post("/analysis-jobs", analysis_payload)
    workflow["analysis_job_create"] = _save_step(case_dir, "analysis_job_create", analysis_job)
    if _is_ok(analysis_job) and isinstance(analysis_job.payload, dict):
        job_id = analysis_job.payload.get("job_id")
        if job_id:
            poll = poll_job(client, case_dir, job_id, timeout_s=timeout_s, interval_s=5.0)
            workflow["analysis_job_poll"] = poll
            final_payload = poll.get("final", {}).get("payload") or {}
            result_id = final_payload.get("result_id")
            if result_id:
                result = client.get(f"/analysis-results/{urllib.parse.quote(result_id)}")
                workflow["analysis_result"] = _save_step(case_dir, "analysis_result", result)
                report = client.get(f"/reports/{urllib.parse.quote(result_id)}")
                workflow["report"] = _save_step(case_dir, "report", report)
                session_payload = {
                    "name": f"Operation Friday Beta - {case['case_id']}",
                    "payload": {
                        "case": case,
                        "target_id": target_id,
                        "product_uri": product_uri,
                        "result_id": result_id,
                    },
                }
                save_session = client.post("/sessions", session_payload)
                workflow["save_session"] = _save_step(case_dir, "save_session", save_session)
                sessions = client.get("/sessions")
                workflow["sessions"] = _save_step(case_dir, "sessions", sessions)

    audit_md, findings = audit_result(case, workflow)
    workflow["audit_findings"] = findings
    workflow["audit_status"] = "pass" if not findings else "review_needed"
    _write_text(case_dir / "audit.md", audit_md)
    _write_json(case_dir / "workflow.json", workflow)
    return workflow


def build_summary(workflows: list[dict[str, Any]]) -> str:
    lines = [
        "# Operation Friday Beta Summary",
        "",
        f"- Cases run: `{len(workflows)}`",
        "",
        "| Case | Mission | Target | Product | Audit | Findings |",
        "| --- | --- | --- | --- | --- | ---: |",
    ]
    for workflow in workflows:
        case = workflow["case"]
        product = workflow.get("selected_product") or {}
        findings = workflow.get("audit_findings") or []
        lines.append(
            "| "
            + " | ".join(
                [
                    case["case_id"],
                    case["mission"],
                    str(workflow.get("selected_target")),
                    str(product.get("product_id")),
                    str(workflow.get("audit_status")),
                    str(len(findings)),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Notes", ""])
    lines.append("- Raw endpoint responses are stored under each case's `raw/` directory.")
    lines.append("- `review_needed` means the automated audit found a possible scientific/API issue to inspect or fix.")
    lines.append(
        "- Per-case audits include API timing, candidate ledger semantics, folded/periodogram health, "
        "depth provenance, and quarantined artifacts."
    )
    lines.append(
        "- Automated `pass` means API/science payload consistency, not confirmed planet validation; "
        "manual visual review lives in `reports/visual-audit/manual-visual-review.md`."
    )
    return "\n".join(lines) + "\n"


def build_summary_payload(workflows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload = []
    for workflow in workflows:
        case = workflow["case"]
        product = workflow.get("selected_product") or {}
        final_poll = (workflow.get("analysis_job_poll") or {}).get("final") or {}
        final_payload = final_poll.get("payload") if isinstance(final_poll, dict) else {}
        payload.append(
            {
                "case_id": case["case_id"],
                "query": case["query"],
                "mission": case["mission"],
                "purpose": case["purpose"],
                "selected_target": workflow.get("selected_target"),
                "selected_product_id": product.get("product_id"),
                "selected_product_uri": product.get("product_uri"),
                "analysis_result_id": (final_payload or {}).get("result_id"),
                "analysis_status": (final_payload or {}).get("status"),
                "audit_status": workflow.get("audit_status"),
                "finding_count": len(workflow.get("audit_findings") or []),
                "audit_path": f"reports/{case['case_id']}/audit.md",
                "workflow_path": f"reports/{case['case_id']}/workflow.json",
                "raw_dir": f"reports/{case['case_id']}/raw",
            }
        )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Operation Friday Beta API-only workflows.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--case", action="append", help="Run only the given case_id. Can be repeated.")
    parser.add_argument("--analysis-timeout", type=float, default=900.0)
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Regenerate Markdown audits from existing workflow.json files.",
    )
    args = parser.parse_args()

    targets = json.loads(TARGETS_PATH.read_text(encoding="utf-8"))
    selected_cases = set(args.case or [])
    if selected_cases:
        targets = [case for case in targets if case["case_id"] in selected_cases]
    if args.report_only:
        workflows = []
        for case in targets:
            workflow_path = REPORTS_DIR / case["case_id"] / "workflow.json"
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            audit_md, findings = audit_result(case, workflow)
            workflow["audit_findings"] = findings
            workflow["audit_status"] = "pass" if not findings else "review_needed"
            _write_text(REPORTS_DIR / case["case_id"] / "audit.md", audit_md)
            _write_json(workflow_path, workflow)
            workflows.append(workflow)
        _write_text(REPORTS_DIR / "operation-summary.md", build_summary(workflows))
        _write_json(REPORTS_DIR / "operation-summary.json", build_summary_payload(workflows))
        return 0 if all(workflow.get("audit_status") == "pass" for workflow in workflows) else 2
    client = ApiClient(args.base_url)
    workflows = [run_case(client, case, timeout_s=args.analysis_timeout) for case in targets]
    _write_text(REPORTS_DIR / "operation-summary.md", build_summary(workflows))
    _write_json(REPORTS_DIR / "operation-summary.json", build_summary_payload(workflows))
    return 0 if all(workflow.get("audit_status") == "pass" for workflow in workflows) else 2


if __name__ == "__main__":
    raise SystemExit(main())
