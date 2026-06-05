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

    status = "complete"
    errors: list[dict[str, str]] = []
    try:
        toi_table = NasaExoplanetArchive.query_criteria(
            table="toi",
            select="toi,tid,tfopwg_disp,pl_orbper,pl_trandep,pl_trandurh,toi_created,rowupdate",
            where=f"tid={tic_id}",
            cache=False,
        )
        toi_rows = _table_rows(toi_table)
        toi_payload = {
            "status": "complete",
            "source": "NASA Exoplanet Archive TOI table, updated from ExoFOP-TESS",
            "match_count": len(toi_rows),
            "matches": toi_rows[:10],
        }
    except Exception as exc:  # pragma: no cover - exercised through monkeypatched archive failures.
        status = "partial"
        errors.append({"table": "toi", "detail": str(exc)})
        toi_payload = {
            "status": "unavailable",
            "source": "NASA Exoplanet Archive TOI table, updated from ExoFOP-TESS",
            "match_count": 0,
            "matches": [],
            "detail": str(exc),
        }

    confirmed_selects = [
        ("pl_name,hostname,tic_id,gaia_id,discoverymethod,disc_year,pl_orbper,pl_rade", []),
        ("pl_name,hostname,tic_id,discoverymethod,disc_year,pl_orbper,pl_rade", ["gaia_id"]),
    ]
    confirmed_rows: list[dict[str, Any]] = []
    confirmed_detail = None
    omitted_columns: list[str] = []
    for select, omitted in confirmed_selects:
        try:
            confirmed_table = NasaExoplanetArchive.query_criteria(
                table="pscomppars",
                select=select,
                where=f"tic_id like '%{tic_id}%'",
                cache=False,
            )
            confirmed_rows = _table_rows(confirmed_table)
            omitted_columns = omitted
            break
        except Exception as exc:  # pragma: no cover - exercised through monkeypatched archive failures.
            confirmed_detail = str(exc)
    else:
        status = "partial"
        errors.append({"table": "pscomppars", "detail": confirmed_detail or "query failed"})

    confirmed_payload = {
        "status": "complete" if confirmed_detail is None or confirmed_rows or omitted_columns else "unavailable",
        "source": "NASA Exoplanet Archive pscomppars TAP table",
        "confirmed_planet_count": len(confirmed_rows),
        "confirmed_planets": confirmed_rows[:10],
    }
    if omitted_columns:
        status = "partial"
        confirmed_payload["status"] = "partial"
        confirmed_payload["omitted_columns"] = omitted_columns
        confirmed_payload["detail"] = (
            "Primary pscomppars query rejected at least one requested column; "
            "retried with a stable confirmed-planet column set."
        )
    elif confirmed_detail and not confirmed_rows:
        confirmed_payload["detail"] = confirmed_detail

    return {
        "status": status,
        "engine": "astroquery.ipac.nexsci.nasa_exoplanet_archive",
        "errors": errors,
        "exofop_toi": toi_payload,
        "nasa_exoplanet_archive": confirmed_payload,
    }


def query_tic_stellar_context(target_id: str) -> dict[str, Any]:
    """Fast, depth-independent TIC stellar lookup.

    Returns only the host-star scalar parameters needed to give the TESS ML
    surface (Nigraha) real stellar context, without the full neighbor/dilution
    sweep or the NASA Exoplanet Archive crossmatch that
    ``query_tic_catalog_context`` performs. This keeps the pre-loop stellar
    enrichment cheap while still supplying real Teff/radius/mass/logg/lum.
    """
    from astropy import units as u
    from astroquery.mast import Catalogs

    requested_tic_id = parse_tic_id(target_id)
    query = f"TIC {requested_tic_id}" if requested_tic_id is not None else str(target_id)
    table = Catalogs.query_object(query, catalog="TIC", radius=21.0 * u.arcsec)
    rows = _table_rows(table)
    if not rows:
        raise RuntimeError(f"TIC catalog returned no rows for {target_id}")

    target_row = None
    if requested_tic_id is not None:
        for row in rows:
            row_id = _text(row, "ID", "TICID", "tic_id")
            if row_id and row_id.isdigit() and int(row_id) == requested_tic_id:
                target_row = row
                break
    target_row = target_row or rows[0]
    target_row_id = _text(target_row, "ID", "TICID", "tic_id")
    resolved_tic_id = int(target_row_id) if target_row_id and target_row_id.isdigit() else requested_tic_id
    return {
        "target_id": resolved_tic_id,
        "query_target_id": requested_tic_id,
        "teff": _number(target_row, "Teff", "teff"),
        "radius_solar": _number(target_row, "rad", "Radius", "radius"),
        "mass_solar": _number(target_row, "mass", "Mass"),
        "logg": _number(target_row, "logg", "logG"),
        "luminosity_solar": _number(target_row, "lum", "luminosity"),
        "source": "TIC",
    }


def query_tic_catalog_context(
    target_id: str,
    *,
    observed_depth: float,
    search_radius_arcsec: float = 120.0,
) -> dict[str, Any]:
    from astropy import units as u
    from astroquery.mast import Catalogs

    requested_tic_id = parse_tic_id(target_id)
    query = f"TIC {requested_tic_id}" if requested_tic_id is not None else str(target_id)
    table = Catalogs.query_object(query, catalog="TIC", radius=search_radius_arcsec * u.arcsec)
    rows = _table_rows(table)
    if not rows:
        raise RuntimeError(f"TIC catalog returned no rows for {target_id}")

    target_row = None
    if requested_tic_id is not None:
        for row in rows:
            row_id = _text(row, "ID", "TICID", "tic_id")
            if row_id and row_id.isdigit() and int(row_id) == requested_tic_id:
                target_row = row
                break
    target_row = target_row or rows[0]
    target_row_id = _text(target_row, "ID", "TICID", "tic_id")
    resolved_tic_id = int(target_row_id) if target_row_id and target_row_id.isdigit() else requested_tic_id
    target_ra = _number(target_row, "ra", "RAJ2000", "RA")
    target_dec = _number(target_row, "dec", "DEJ2000", "DEC")
    target_tmag = _number(target_row, "Tmag", "tmag", "TESSmag")
    target_teff = _number(target_row, "Teff", "teff")
    target_radius = _number(target_row, "rad", "Radius", "radius")
    target_mass = _number(target_row, "mass", "Mass")
    target_logg = _number(target_row, "logg", "logG")
    target_lum = _number(target_row, "lum", "luminosity")
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
        is_target = bool(
            resolved_tic_id is not None and row_tic and row_tic.isdigit() and int(row_tic) == resolved_tic_id
        )
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
    archive_context = _query_nasa_archive_context(resolved_tic_id)
    context_status = "complete" if archive_context.get("status") == "complete" else "partial"
    return {
        "status": context_status,
        "engine": "astroquery.mast.Catalogs TIC",
        "archive_context": {
            "status": archive_context.get("status"),
            "engine": archive_context.get("engine"),
            "errors": archive_context.get("errors", []),
        },
        "tic": {
            "target_id": resolved_tic_id,
            "query_target_id": requested_tic_id,
            "ra": target_ra,
            "dec": target_dec,
            "tmag": target_tmag,
            "gaia_id": _text(target_row, "GAIA", "gaia", "GAIA_DR3"),
            "stellar": {
                "teff": target_teff,
                "radius_solar": target_radius,
                "mass_solar": target_mass,
                "logg": target_logg,
                "luminosity_solar": target_lum,
                "source": "TIC",
            },
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
