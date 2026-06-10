#!/usr/bin/env python3
"""Unmocked live science verification against real planet names.

Drives the real OrbitLab API end-to-end (search by planet name -> products ->
paper-grade analysis job -> result) and compares the recovered ephemerides and
physics against NASA Exoplanet Archive golden values. No mocks anywhere: real
MAST products, real engines (TLS, DAVE ModShift, SWEET, TRICERATOPS, ML
artifacts when registered).

The script collects evidence; the final scientific judgement (period, depth,
radius, disposition semantics) is reviewed manually against the golden table.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# NASA Exoplanet Archive golden values (pscomppars, 2026-06).
GOLDEN_TARGETS: list[dict[str, Any]] = [
    {
        "query": "L 98-59",
        "mission": "TESS",
        "preferred_product_substring": "s0002-0000000307210830-0121",
        "vetting_mode": "paper",
        "known_planets": [
            {"name": "L 98-59 b", "period_days": 2.2531136, "radius_earth": 0.85},
            {"name": "L 98-59 c", "period_days": 3.6906777, "radius_earth": 1.385},
            {"name": "L 98-59 d", "period_days": 7.4512630, "radius_earth": 1.521},
        ],
        "stellar_radius_solar": 0.303,
        "notes": "M3V multi-planet system; single sector cannot confirm d's 7.45 d with >=2 transits near edges.",
    },
    {
        "query": "WASP-126",
        "mission": "TESS",
        "preferred_product_substring": "s0001-0000000025155310-0120",
        "vetting_mode": "paper",
        "known_planets": [
            {"name": "WASP-126 b", "period_days": 3.2888, "radius_earth": 10.8},
        ],
        "stellar_radius_solar": 1.27,
        "notes": "Hot Jupiter, ~6000 ppm depth; classic deep-transit case that symmetric clipping used to delete.",
    },
    {
        "query": "Kepler-10",
        "mission": "Kepler",
        "preferred_product_substring": "kplr011904151",
        "vetting_mode": "paper",
        "known_planets": [
            {"name": "Kepler-10 b", "period_days": 0.837495, "radius_earth": 1.47},
            {"name": "Kepler-10 c", "period_days": 45.294301, "radius_earth": 2.35},
        ],
        "stellar_radius_solar": 1.056,
        "notes": "Kepler path; 10 b is an 0.84 d ultra-short-period rocky planet, ~152 ppm depth.",
    },
]

PERIOD_MATCH_FRACTION = 0.02


def _request(base_url: str, method: str, path: str, payload: dict | None = None, timeout: float = 300.0):
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{base_url}{path}", data=body, headers=headers, method=method)
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else None, time.perf_counter() - started


def _match_known_planet(period_days: float | None, known_planets: list[dict[str, Any]]):
    if not isinstance(period_days, (int, float)) or period_days <= 0:
        return None, None
    for planet in known_planets:
        truth = planet["period_days"]
        for alias, label in ((1.0, "exact"), (0.5, "half_period_alias"), (2.0, "double_period_alias")):
            if abs(period_days - truth * alias) / (truth * alias) <= PERIOD_MATCH_FRACTION:
                return planet, label
    return None, None


def _verify_target(base_url: str, spec: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    case_dir = output_dir / spec["query"].replace(" ", "_").lower()
    case_dir.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {"query": spec["query"], "mission": spec["mission"], "steps": {}}

    search, elapsed = _request(
        base_url, "GET", f"/search?query={urllib.parse.quote(spec['query'])}&mission={spec['mission']}"
    )
    record["steps"]["search"] = {"elapsed_s": elapsed, "result_count": len(search or [])}
    if not search:
        record["status"] = "failed"
        record["detail"] = "search returned no targets"
        return record
    target_id = search[0]["target_id"] if isinstance(search[0], dict) else None
    record["target_id"] = target_id

    products, elapsed = _request(
        base_url, "GET", f"/targets/{urllib.parse.quote(str(target_id))}/products?mission={spec['mission']}"
    )
    record["steps"]["products"] = {"elapsed_s": elapsed, "product_count": len(products or [])}
    if not products:
        record["status"] = "failed"
        record["detail"] = "no products returned"
        return record
    product = next(
        (p for p in products if spec["preferred_product_substring"] in str(p.get("product_uri", ""))),
        products[0],
    )
    record["product_uri"] = product.get("product_uri")

    job, elapsed = _request(
        base_url,
        "POST",
        "/analysis-jobs",
        {
            "target_id": target_id,
            "product_uri": product["product_uri"],
            "mission": spec["mission"],
            "vetting_mode": spec["vetting_mode"],
            "max_candidates": 2,
        },
    )
    record["steps"]["analysis_job_create"] = {"elapsed_s": elapsed, "job_id": job.get("job_id")}

    status = job.get("status")
    polls = 0
    while status in {"queued", "running"} and polls < 720:
        time.sleep(5)
        polls += 1
        job, _ = _request(base_url, "GET", f"/analysis-jobs/{job['job_id']}")
        status = job.get("status")
    record["steps"]["analysis_job_poll"] = {"polls": polls, "final_status": status}
    if status != "complete":
        record["status"] = "failed"
        record["detail"] = f"job ended as {status}: {job.get('error')}"
        return record

    result, elapsed = _request(base_url, "GET", f"/analysis-results/{job['result_id']}")
    record["steps"]["analysis_result"] = {"elapsed_s": elapsed}
    (case_dir / "analysis_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    tces = result.get("tces") or []
    ledger = []
    matched_planets: dict[str, dict[str, Any]] = {}
    for tce in tces:
        planet, alias = _match_known_planet(tce.get("period_days"), spec["known_planets"])
        physics = tce.get("physics") or {}
        row = {
            "candidate_id": tce.get("candidate_id"),
            "period_days": tce.get("period_days"),
            "depth_ppm": tce.get("depth_ppm"),
            "snr": tce.get("signal_to_noise"),
            "effective_snr": tce.get("effective_snr"),
            "disposition": tce.get("disposition"),
            "action_label": tce.get("action_label"),
            "matched_known_planet": planet["name"] if planet else None,
            "period_match_kind": alias,
            "expected_period_days": planet["period_days"] if planet else None,
            "measured_radius_earth": physics.get("planet_radius_earth"),
            "expected_radius_earth": planet["radius_earth"] if planet else None,
            "interpretation_locked": physics.get("interpretation_locked"),
            "stellar_context_source": physics.get("stellar_context_source"),
            "hard_fail_flags": [
                f.get("code") for f in (tce.get("flags") or []) if f.get("severity") == "hard_fail"
            ],
            "warning_flags": [
                f.get("code") for f in (tce.get("flags") or []) if f.get("severity") == "warning"
            ],
            "fpp_status": (tce.get("fpp") or {}).get("status"),
            "fpp": (tce.get("fpp") or {}).get("fpp"),
            "nfpp": (tce.get("fpp") or {}).get("nfpp"),
            "tls_sde": ((tce.get("evidence") or {}).get("tls") or {}).get("sde"),
            "model_shift_status": ((tce.get("vetting") or {}).get("model_shift") or {}).get("status"),
            "ml_probability": (tce.get("ml") or {}).get("probability"),
            "paper_grade_status": ((tce.get("vetting") or {}).get("paper_grade") or {}).get("status"),
        }
        ledger.append(row)
        if planet and planet["name"] not in matched_planets:
            matched_planets[planet["name"]] = row

    record["ledger"] = ledger
    record["planet_candidate_count"] = len(result.get("planet_candidates") or [])
    record["matched_known_planets"] = sorted(matched_planets)
    record["false_rejections"] = [
        row["candidate_id"]
        for row in ledger
        if row["matched_known_planet"]
        and row["period_match_kind"] == "exact"
        and row["disposition"] == "rejected_signal"
    ]
    record["stellar_context"] = result.get("stellar_context")
    record["status"] = "complete"
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Unmocked live verification against real planet names.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--output-dir", default=".orbitlab/benchmarks/live-planet-verification")
    parser.add_argument("--queries", nargs="*", default=None, help="subset of golden queries to run")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for spec in GOLDEN_TARGETS:
        if args.queries and spec["query"] not in args.queries:
            continue
        print(f"=== live verification: {spec['query']} ({spec['mission']}) ===", flush=True)
        try:
            record = _verify_target(args.base_url, spec, output_dir)
        except Exception as exc:  # keep evidence of partial failures
            record = {"query": spec["query"], "status": "failed", "detail": f"{exc.__class__.__name__}: {exc}"}
        records.append(record)
        print(json.dumps({k: v for k, v in record.items() if k != "ledger"}, indent=2, default=str), flush=True)

    summary_path = output_dir / "live_verification_summary.json"
    summary_path.write_text(json.dumps(records, indent=2, default=str), encoding="utf-8")
    print(f"summary written to {summary_path}", flush=True)
    failed = [r for r in records if r.get("status") != "complete" or r.get("false_rejections")]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
