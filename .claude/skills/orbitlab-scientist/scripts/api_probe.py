#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def request_json(base_url: str, path: str, *, payload: dict[str, Any] | None = None) -> Any:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def _tce_audit(tce: dict[str, Any]) -> dict[str, Any]:
    """Extract per-TCE audit fields for the summary."""
    validation = tce.get("validation") or {}
    thresholds = tce.get("thresholds") or {}
    flags = tce.get("flags") or []
    hard_fails = [f["code"] for f in flags if isinstance(f, dict) and f.get("severity") == "hard_fail"]
    warnings = [f["code"] for f in flags if isinstance(f, dict) and f.get("severity") == "warning"]
    return {
        "period": tce.get("period"),
        "depth": tce.get("depth"),
        "disposition": tce.get("disposition"),
        "snr": validation.get("snr"),
        "odd_even_sigma": validation.get("odd_even_sigma"),
        "secondary_eclipse_snr": validation.get("secondary_eclipse_snr"),
        "centroid_significance": validation.get("centroid_significance"),
        "centroid_shift_pixels": validation.get("centroid_shift_pixels"),
        "sibling_signals_masked": validation.get("sibling_signals_masked"),
        "known_planet": tce.get("known_planet"),
        "period_alias_code": tce.get("period_alias_code"),
        "sde": tce.get("tls_sde"),
        "sde_population_bin": thresholds.get("sde_population_bin"),
        "tls_sde_threshold_used": thresholds.get("tls_sde_threshold_used"),
        "sde_threshold_source": thresholds.get("sde_threshold_source"),
        "ml_score": tce.get("ml_score"),
        "ml_domain": tce.get("ml_domain"),
        "ml_available": tce.get("ml_available"),
        "triceratops_fpp": (tce.get("triceratops") or {}).get("fpp"),
        "triceratops_nfpp": (tce.get("triceratops") or {}).get("nfpp"),
        "hard_fails": hard_fails,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe OrbitLab's live API science path.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--target", required=True)
    parser.add_argument("--mission", choices=("TESS", "Kepler", "K2"), default="TESS")
    parser.add_argument("--product-substring")
    parser.add_argument("--mode", choices=("fast", "deep", "paper"), default="paper")
    parser.add_argument("--max-candidates", type=int, default=2)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    health = request_json(args.base_url, "/health")
    query = urllib.parse.quote(args.target)
    search = request_json(args.base_url, f"/search?query={query}&mission={args.mission}")
    if not search:
        raise RuntimeError(f"No target matches for {args.target!r}")
    target_id = search[0]["target_id"]
    encoded_target = urllib.parse.quote(target_id, safe="")
    products = request_json(args.base_url, f"/targets/{encoded_target}/products?mission={args.mission}")
    product = next(
        (item for item in products if args.product_substring and args.product_substring in item["product_uri"]),
        products[0] if products else None,
    )
    if product is None:
        raise RuntimeError(f"No products for {target_id!r}")

    job = request_json(
        args.base_url,
        "/analysis-jobs",
        payload={
            "target_id": target_id,
            "product_uri": product["product_uri"],
            "mission": args.mission,
            "vetting_mode": args.mode,
            "max_candidates": args.max_candidates,
        },
    )
    job_id = job["job_id"]
    for _ in range(720):
        status = request_json(args.base_url, f"/analysis-jobs/{job_id}")
        if status["status"] == "complete":
            result = request_json(args.base_url, f"/analysis-results/{status['result_id']}")
            record = {"health": health, "target": search[0], "product": product, "job": status, "result": result}
            text = json.dumps(record, indent=2)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(text + "\n", encoding="utf-8")
            tces = result.get("tces") or []
            summary = {
                "status": status["status"],
                "target_id": target_id,
                "product_uri": product["product_uri"],
                "result_id": status["result_id"],
                "science_readiness": (result.get("science_readiness") or {}).get("status"),
                "tce_count": len(tces),
                "planet_candidate_count": len(result.get("planet_candidates") or []),
                "tce_audit": [_tce_audit(t) for t in tces],
                "output": str(args.output) if args.output else None,
            }
            print(json.dumps(summary, indent=2))
            return 0
        if status["status"] == "failed":
            raise RuntimeError(status.get("error") or "Analysis job failed")
        time.sleep(2)
    raise TimeoutError(f"Analysis job {job_id} did not finish")


if __name__ == "__main__":
    raise SystemExit(main())
