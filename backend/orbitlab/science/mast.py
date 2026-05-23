from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from orbitlab.config import settings
from orbitlab.science.data_quality import clean_light_curve
from orbitlab.science.tpf_diagnostics import TpfLightCurveBundle


@dataclass(frozen=True)
class ProductSummary:
    product_id: str
    mission: str
    description: str
    size: int | None
    product_uri: str


TARGET_ALIASES = {
    "trappist": "TRAPPIST-1",
    "trappist 1": "TRAPPIST-1",
    "trappist-1": "TRAPPIST-1",
    "trappist1": "TRAPPIST-1",
}


def resolve_target_alias(query: str) -> str | None:
    normalized = " ".join(query.strip().lower().split())
    return TARGET_ALIASES.get(normalized)


def row_value(row, key: str, default=None):
    colnames = set(getattr(row, "colnames", []))
    if key in colnames:
        return row[key]
    try:
        # Fallback for dict-like rows or structured arrays
        return row[key]
    except Exception:
        return default


def search_targets(query: str, *, mission: str | None = None, limit: int = 20) -> list[dict]:
    query = query.strip()
    try:
        from astroquery.mast import Catalogs
    except ImportError as exc:  # pragma: no cover - optional science install
        raise RuntimeError("astroquery is required for live MAST target search") from exc
    mission_upper = (mission or "").upper()
    if mission_upper == "KEPLER":
        catalog = "KIC"
    elif mission_upper == "K2":
        catalog = "EPIC"
    else:
        catalog = "TIC"
    results: list[dict] = []
    alias_target = resolve_target_alias(query)
    if alias_target:
        results.append(
            {
                "target_id": alias_target,
                "ra": None,
                "dec": None,
                "catalog": "ALIAS",
                "match_type": "alias",
                "matched_query": query,
            }
        )
    if query and not query.isdigit() and not alias_target:
        results.append(
            {
                "target_id": query,
                "ra": None,
                "dec": None,
                "catalog": "NAME",
                "match_type": "catalog",
                "matched_query": None,
            }
        )
    try:
        table = Catalogs.query_object(query, catalog=catalog, radius=0.02)
    except Exception:
        if alias_target:
            return results
        if mission_upper not in {"KEPLER", "K2"}:
            raise
        return results or [
            {
                "target_id": query,
                "ra": None,
                "dec": None,
                "catalog": catalog,
                "match_type": "catalog",
                "matched_query": None,
            }
        ]
    rows = table[:limit]
    seen = {(item["catalog"], item["target_id"]) for item in results}
    for row in rows:
        item = {
            "target_id": str(row_value(row, "ID", row_value(row, "TICID", ""))),
            "ra": float(row_value(row, "ra")) if "ra" in row.colnames else None,
            "dec": float(row_value(row, "dec")) if "dec" in row.colnames else None,
            "catalog": catalog,
            "match_type": "catalog",
            "matched_query": None,
        }
        key = (item["catalog"], item["target_id"])
        if key not in seen:
            results.append(item)
            seen.add(key)
    return results


def list_tpf_products(target_id: str, *, mission: str | None = None) -> list[ProductSummary]:
    try:
        import lightkurve as lk
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("lightkurve is required for live TPF product search") from exc
    target_name = target_id.strip()
    mission_upper = (mission or "").upper()
    if target_name.isdigit():
        if mission_upper == "TESS":
            target_name = f"TIC {target_name}"
        elif mission_upper == "KEPLER":
            target_name = f"KIC {target_name}"
        elif mission_upper == "K2":
            target_name = f"EPIC {target_name}"

    search = lk.search_targetpixelfile(target_name, mission=mission)
    if len(search) > 0:
        summaries: list[ProductSummary] = []
        for row in search.table:
            product_uri = str(row_value(row, "dataURI", "") or "")
            if not product_uri:
                continue
            filename = str(row_value(row, "productFilename", row_value(row, "obs_id", "")))
            description = str(row_value(row, "description", "Target Pixel File"))
            summaries.append(
                ProductSummary(
                    product_id=str(row_value(row, "obsID", row_value(row, "obs_id", filename))),
                    mission=str(row_value(row, "mission", row_value(row, "obs_collection", mission or ""))),
                    description=description,
                    size=int(row_value(row, "size")) if row_value(row, "size") else None,
                    product_uri=product_uri,
                )
            )
        return summaries

    try:
        from astroquery.mast import Observations
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("astroquery is required for live MAST product listing") from exc
    criteria = {"target_name": target_name, "dataproduct_type": "timeseries"}
    if mission:
        criteria["obs_collection"] = "Kepler" if mission == "K2" else mission
    obs = Observations.query_criteria(**criteria)
    if len(obs) == 0:
        return []
    products = Observations.get_product_list(obs)
    if len(products) == 0:
        return []
    summaries: list[ProductSummary] = []
    for row in products:
        product_uri = str(row_value(row, "dataURI", "") or "")
        if not product_uri:
            continue
        description = str(row_value(row, "description", ""))
        filename = str(row_value(row, "productFilename", ""))
        product_type = str(row_value(row, "productType", ""))
        lower_name = filename.lower()
        is_tpf = (
            "target pixel" in description.lower()
            or "targetpixel" in description.lower()
            or "tpf" in lower_name
            or lower_name.endswith("_tp.fits")
            or "target pixel" in product_type.lower()
        )
        if not is_tpf:
            continue
        summaries.append(
            ProductSummary(
                product_id=str(row_value(row, "obsID", row_value(row, "obs_id", filename))),
                mission=str(row_value(row, "obs_collection", mission or "")),
                description=description,
                size=int(row_value(row, "size")) if row_value(row, "size") else None,
                product_uri=product_uri,
            )
        )
    return summaries


def _download_mast_product(product_uri: str, cache_dir: Path) -> Path:
    try:
        from astroquery.mast import Observations
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("astroquery is required for MAST product downloads") from exc
    safe_cache_dir = cache_dir.resolve()
    safe_cache_dir.mkdir(parents=True, exist_ok=True)
    filename = Path(product_uri.rsplit("/", 1)[-1].replace(":", "_")).name or "mast-product.fits"
    destination = safe_cache_dir / filename
    manifest = Observations.download_file(product_uri, local_path=str(destination), cache=True)
    if isinstance(manifest, str):
        candidate = Path(manifest)
    else:
        candidate = Path(str(manifest))
    if candidate.is_dir():
        candidate_dir = _resolve_path_within_directory(candidate, safe_cache_dir)
        fits_files = sorted(candidate_dir.rglob("*.fits"))
        if not fits_files:
            raise FileNotFoundError(f"MAST download produced no FITS files under {candidate_dir}")
        return fits_files[0]
    if not candidate.exists() and destination.exists():
        return destination
    if not candidate.exists() and product_uri.startswith("mast:"):
        fits_files = sorted(safe_cache_dir.rglob("*.fits"))
        if fits_files:
            return fits_files[-1]
    if not candidate.exists():
        raise FileNotFoundError(f"MAST product download did not create a readable file: {product_uri}")
    return _resolve_path_within_directory(candidate, safe_cache_dir)


def _resolve_path_within_directory(path: Path, root: Path) -> Path:
    resolved_root = root.resolve()
    resolved_path = path.expanduser().resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise PermissionError(f"TPF path must be inside the configured MAST cache: {resolved_root}") from exc
    return resolved_path


def _resolve_existing_cache_path(product_uri: str, root: Path) -> Path:
    resolved_root = root.resolve()
    raw_path = Path(product_uri).expanduser()
    candidate = raw_path if raw_path.is_absolute() else resolved_root / raw_path
    unresolved_candidate = candidate.resolve(strict=False)
    try:
        unresolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise PermissionError(f"TPF path must be inside the configured MAST cache: {resolved_root}") from exc
    if not candidate.exists():
        raise FileNotFoundError(f"TPF path or MAST URI is not readable: {product_uri}")
    return _resolve_path_within_directory(candidate, resolved_root)


def resolve_tpf_path(product_uri: str, *, cache_dir: Path | None = None) -> Path:
    safe_cache_dir = (cache_dir or settings.mast_cache_dir).resolve()
    if product_uri.startswith("mast:"):
        return _download_mast_product(product_uri, safe_cache_dir)
    return _resolve_existing_cache_path(product_uri, safe_cache_dir)


def _mask_from_tpf(tpf, aperture_mask: np.ndarray | list[list[bool]] | str | None):
    if isinstance(aperture_mask, list):
        mask = np.asarray(aperture_mask, dtype=bool)
        if mask.shape != tuple(tpf.flux.shape[1:]):
            raise ValueError(f"aperture mask shape {mask.shape} does not match TPF shape {tuple(tpf.flux.shape[1:])}")
        if not mask.any():
            raise ValueError("aperture mask must select at least one pixel")
        return mask, np.asarray(getattr(tpf, "pipeline_mask", []), dtype=bool), None
    if aperture_mask == "pipeline":
        pipeline_mask = np.asarray(getattr(tpf, "pipeline_mask", []), dtype=bool)
        mask = pipeline_mask
        threshold_mask = None
        if mask.shape != tuple(tpf.flux.shape[1:]) or not mask.any():
            threshold_mask = np.asarray(tpf.create_threshold_mask(threshold=3), dtype=bool)
            mask = threshold_mask
        if mask.shape != tuple(tpf.flux.shape[1:]) or not mask.any():
            raise ValueError("TPF has no usable pipeline or threshold aperture pixels")
        return mask, pipeline_mask, threshold_mask
    return aperture_mask, np.asarray(getattr(tpf, "pipeline_mask", []), dtype=bool), None


def _tpf_pixel_scale_arcsec(tpf) -> float | None:
    for attr in ("wcs",):
        wcs = getattr(tpf, attr, None)
        if wcs is None:
            continue
        try:
            scales = np.asarray(wcs.proj_plane_pixel_scales(), dtype=float)
            if scales.size:
                return float(np.nanmedian(np.abs(scales)) * 3600.0)
        except Exception:
            pass
    mission = str(getattr(tpf, "mission", "")).upper()
    if "TESS" in mission:
        return 21.0
    if "KEPLER" in mission or "K2" in mission:
        return 3.98
    return None


def extract_light_curve_bundle_from_tpf(
    product_uri: str,
    aperture_mask: np.ndarray | list[list[bool]] | str | None = "pipeline",
) -> TpfLightCurveBundle:
    try:
        import lightkurve as lk
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("lightkurve is required for TPF extraction") from exc
    tpf_path = resolve_tpf_path(product_uri)
    tpf = lk.read(str(tpf_path))
    if not hasattr(tpf, "to_lightcurve"):
        raise TypeError(f"file is not a Lightkurve target pixel file: {tpf_path}")
    mask, pipeline_mask, threshold_mask = _mask_from_tpf(tpf, aperture_mask)
    lc = tpf.to_lightcurve(aperture_mask=mask)
    quality = getattr(lc, "quality", None)
    time = np.asarray(lc.time.value, dtype=np.float32)
    flux = np.asarray(lc.flux.value, dtype=np.float32)
    quality_arr = np.asarray(quality) if quality is not None else None
    clean_light_curve(time, flux, quality_arr)
    pixel_flux = np.asarray(tpf.flux.value, dtype=np.float32) if hasattr(getattr(tpf, "flux", None), "value") else None
    return TpfLightCurveBundle(
        time=time,
        flux=flux,
        quality=quality_arr,
        pixel_flux=pixel_flux,
        selected_mask=np.asarray(mask, dtype=bool) if mask is not None else None,
        pipeline_mask=pipeline_mask if pipeline_mask.shape == tuple(tpf.flux.shape[1:]) else None,
        threshold_mask=threshold_mask if threshold_mask is not None else None,
        pixel_scale_arcsec=_tpf_pixel_scale_arcsec(tpf),
        reference_row=float(getattr(tpf, "row", np.nan)) if np.isfinite(getattr(tpf, "row", np.nan)) else None,
        reference_column=float(getattr(tpf, "column", np.nan)) if np.isfinite(getattr(tpf, "column", np.nan)) else None,
    )


def extract_light_curve_from_tpf(
    product_uri: str,
    aperture_mask: np.ndarray | list[list[bool]] | str | None = "pipeline",
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    bundle = extract_light_curve_bundle_from_tpf(product_uri, aperture_mask=aperture_mask)
    return bundle.time, bundle.flux, bundle.quality
