#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

TAP_BASE = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
API_BASE = "https://exoplanetarchive.ipac.caltech.edu/cgi-bin/nstedAPI/nph-nstedAPI"
DEFAULT_QUERIES = {
    "tess": (
        "select toi,tfopwg_disp,pl_orbper,pl_trandurh,pl_trandep,st_teff,"
        "st_rad,st_logg from toi where tfopwg_disp is not null"
    ),
    "kepler": (
        "select kepid,tce_plnt_num,tce_period,tce_duration,tce_depth,"
        "tce_max_mult_ev,av_pp_pc,av_training_set,av_pred_class from q1_q17_dr24_tce"
    ),
}


def _write_checked_csv(url: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(url, timeout=120) as response:
        payload = response.read()
    output.write_bytes(payload)
    with output.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
    if not header or header[0].startswith("ERROR"):
        raise RuntimeError(f"downloaded calibration source is empty or invalid: {output}")


def fetch_tap_csv(query: str, output: Path) -> None:
    url = f"{TAP_BASE}?{urlencode({'query': query, 'format': 'csv'})}"
    _write_checked_csv(url, output)


def fetch_legacy_api_csv(table: str, select: str, output: Path) -> None:
    url = f"{API_BASE}?{urlencode({'table': table, 'select': select, 'format': 'csv'})}"
    _write_checked_csv(url, output)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch public calibration-label tables for OrbitLab probability calibration."
    )
    parser.add_argument("mission", choices=sorted(DEFAULT_QUERIES))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--query", default=None, help="Override the default NASA Exoplanet Archive TAP query.")
    args = parser.parse_args()
    output = args.output or Path(f".orbitlab/calibration/raw/{args.mission}-calibration-source.csv")
    query = args.query or DEFAULT_QUERIES[args.mission]
    if args.mission == "kepler" and args.query is None:
        select, table = query.removeprefix("select ").split(" from ", 1)
        fetch_legacy_api_csv(table, select, output)
    else:
        fetch_tap_csv(query, output)
    print(output)


if __name__ == "__main__":
    main()
