from __future__ import annotations

import math
import re
from typing import Any

import numpy as np


def parse_tic_id(target_id: str) -> int | None:
    match = re.search(r"(?:TIC\s*)?(\d{5,})", str(target_id), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _table_rows(table: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in table:
        payload: dict[str, Any] = {}
        for name in table.colnames:
            value = row[name]
            try:
                if hasattr(value, "item"):
                    value = value.item()
            except ValueError:
                pass
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="replace")
            payload[name] = value
        rows.append(payload)
    return rows


def _number(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key not in row:
            continue
        try:
            value = float(row[key])
        except (TypeError, ValueError):
            continue
        if np.isfinite(value):
            return value
    return None


def _text(row: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text and text != "--":
            return text
    return None


def _angular_separation_arcsec(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    ra1_r, dec1_r, ra2_r, dec2_r = map(math.radians, (ra1, dec1, ra2, dec2))
    sin_ddec = math.sin((dec2_r - dec1_r) / 2.0)
    sin_dra = math.sin((ra2_r - ra1_r) / 2.0)
    a = sin_ddec**2 + math.cos(dec1_r) * math.cos(dec2_r) * sin_dra**2
    return math.degrees(2.0 * math.asin(min(1.0, math.sqrt(max(0.0, a))))) * 3600.0


def _query_nasa_archive_context(tic_id: int | None) -> dict[str, Any]:
    if tic_id is None:
        raise RuntimeError("NASA Exoplanet Archive context requires a numeric TIC ID")

    from astroquery.ipac.nexsci.nasa_exoplanet_archive import NasaExoplanetArchive

    toi_table = NasaExoplanetArchive.query_criteria(
        table="toi",
        select="toi,tid,tfopwg_disp,pl_orbper,pl_trandep,pl_trandurh,toi_created,rowupdate",
        where=f"tid={tic_id}",
        cache=False,
    )
    confirmed_table = NasaExoplanetArchive.query_criteria(
        table="pscomppars",
        select="pl_name,hostname,tic_id,gaia_id,discoverymethod,disc_year,pl_orbper,pl_rade",
        where=f"tic_id like '%{tic_id}%'",
        cache=False,
    )
    toi_rows = _table_rows(toi_table)
    confirmed_rows = _table_rows(confirmed_table)
    return {
        "status": "complete",
        "engine": "astroquery.ipac.nexsci.nasa_exoplanet_archive",
        "exofop_toi": {
            "status": "complete",
            "source": "NASA Exoplanet Archive TOI table, updated from ExoFOP-TESS",
            "match_count": len(toi_rows),
            "matches": toi_rows[:10],
        },
        "nasa_exoplanet_archive": {
            "status": "complete",
            "source": "NASA Exoplanet Archive pscomppars TAP table",
            "confirmed_planet_count": len(confirmed_rows),
            "confirmed_planets": confirmed_rows[:10],
        },
    }


def query_tic_catalog_context(
    target_id: str,
    *,
    observed_depth: float,
    search_radius_arcsec: float = 120.0,
) -> dict[str, Any]:
    from astropy import units as u
    from astroquery.mast import Catalogs

    tic_id = parse_tic_id(target_id)
    query = f"TIC {tic_id}" if tic_id is not None else str(target_id)
    table = Catalogs.query_object(query, catalog="TIC", radius=search_radius_arcsec * u.arcsec)
    rows = _table_rows(table)
    if not rows:
        raise RuntimeError(f"TIC catalog returned no rows for {target_id}")

    target_row = None
    if tic_id is not None:
        for row in rows:
            row_id = _text(row, "ID", "TICID", "tic_id")
            if row_id and row_id.isdigit() and int(row_id) == tic_id:
                target_row = row
                break
    target_row = target_row or rows[0]
    target_ra = _number(target_row, "ra", "RAJ2000", "RA")
    target_dec = _number(target_row, "dec", "DEJ2000", "DEC")
    target_tmag = _number(target_row, "Tmag", "tmag", "TESSmag")
    if target_ra is None or target_dec is None:
        raise RuntimeError(f"TIC catalog row for {target_id} does not include coordinates")

    neighbors = []
    contaminant_capable = []
    for row in rows:
        ra = _number(row, "ra", "RAJ2000", "RA")
        dec = _number(row, "dec", "DEJ2000", "DEC")
        if ra is None or dec is None:
            continue
        row_tic = _text(row, "ID", "TICID", "tic_id")
        separation = _angular_separation_arcsec(target_ra, target_dec, ra, dec)
        tmag = _number(row, "Tmag", "tmag", "TESSmag")
        delta_mag = tmag - target_tmag if tmag is not None and target_tmag is not None else None
        flux_ratio = 10 ** (-0.4 * delta_mag) if delta_mag is not None else None
        max_diluted_depth = flux_ratio / (1.0 + flux_ratio) if flux_ratio is not None else None
        is_target = bool(tic_id is not None and row_tic and row_tic.isdigit() and int(row_tic) == tic_id)
        capable = bool(not is_target and max_diluted_depth is not None and observed_depth <= max_diluted_depth)
        neighbor = {
            "tic_id": row_tic,
            "gaia_id": _text(row, "GAIA", "gaia", "GAIA_DR3"),
            "ra": ra,
            "dec": dec,
            "separation_arcsec": separation,
            "tmag": tmag,
            "delta_tmag": delta_mag,
            "flux_ratio": flux_ratio,
            "max_diluted_eclipse_depth": max_diluted_depth,
            "can_mimic_observed_depth": capable,
            "is_target": is_target,
        }
        neighbors.append(neighbor)
        if capable:
            contaminant_capable.append(neighbor)

    neighbors.sort(key=lambda row: row["separation_arcsec"])
    archive_context = _query_nasa_archive_context(tic_id)
    return {
        "status": "complete",
        "engine": "astroquery.mast.Catalogs TIC",
        "tic": {
            "target_id": tic_id,
            "ra": target_ra,
            "dec": target_dec,
            "tmag": target_tmag,
            "gaia_id": _text(target_row, "GAIA", "gaia", "GAIA_DR3"),
        },
        "gaia": {
            "status": "complete",
            "source": "TIC crossmatch GAIA column",
            "target_gaia_id": _text(target_row, "GAIA", "gaia", "GAIA_DR3"),
        },
        "nearby_sources": neighbors[:25],
        "exofop_toi": archive_context["exofop_toi"],
        "nasa_exoplanet_archive": archive_context["nasa_exoplanet_archive"],
        "contamination": {
            "status": "pass" if not contaminant_capable else "warning",
            "observed_depth": observed_depth,
            "capable_neighbor_count": len(contaminant_capable),
            "capable_neighbors": contaminant_capable[:10],
        },
        "search_radius_arcsec": search_radius_arcsec,
    }
