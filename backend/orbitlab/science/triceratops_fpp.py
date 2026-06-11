from __future__ import annotations

import os
import re
import shutil
import ssl
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np

from orbitlab.config import settings
from orbitlab.science.bls import TransitCandidate
from orbitlab.science.catalog_context import parse_tic_id

# The TRILEGAL service at stev.oapd.inaf.it serves a valid ZeroSSL leaf
# certificate but omits the intermediate, so default verification fails with
# "unable to get local issuer certificate". Appending the publicly published
# intermediate (AIA-chased, exactly what browsers do) repairs the chain
# client-side; verification still has to anchor at a trusted certifi root, so
# this never weakens trust the way verify=False would.
_ZEROSSL_INTERMEDIATE_URL = "http://crt.sectigo.com/ZeroSSLRSADVSSLCA2.crt"
_CA_ENV_KEYS = ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE")


def _calibration_dir() -> Path:
    return settings.calibration_dir


def ensure_trilegal_ca_bundle() -> Path | None:
    """Build (once) a certifi bundle with the missing TRILEGAL intermediate."""
    bundle_path = _calibration_dir() / "trilegal-ca-bundle.pem"
    if bundle_path.exists():
        return bundle_path
    try:
        import certifi

        with urllib.request.urlopen(_ZEROSSL_INTERMEDIATE_URL, timeout=30) as response:
            intermediate_der = response.read()
        intermediate_pem = ssl.DER_cert_to_PEM_cert(intermediate_der)
        base_bundle = Path(certifi.where()).read_text(encoding="utf-8")
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text(
            base_bundle
            + "\n# ZeroSSL RSA DV SSL CA 2 intermediate (AIA-chased for stev.oapd.inaf.it;"
            + " chains must still anchor at a certifi root above)\n"
            + intermediate_pem,
            encoding="utf-8",
        )
        return bundle_path
    except Exception:
        return None


@contextmanager
def _repaired_ca_environment(bundle_path: Path | None):
    """Point requests- and ssl-default-context verification at the repaired bundle."""
    if bundle_path is None:
        yield
        return
    saved = {key: os.environ.get(key) for key in _CA_ENV_KEYS}
    for key in _CA_ENV_KEYS:
        os.environ[key] = str(bundle_path)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _cached_trilegal_path(tic_id: int) -> Path:
    return _calibration_dir() / "trilegal" / f"{tic_id}_TRILEGAL.csv"


def _harvest_trilegal_result(tic_id: int) -> bool:
    """Move a freshly downloaded {tic}_TRILEGAL.csv from CWD into the cache."""
    produced = Path.cwd() / f"{tic_id}_TRILEGAL.csv"
    if not produced.exists():
        return False
    cached = _cached_trilegal_path(tic_id)
    try:
        cached.parent.mkdir(parents=True, exist_ok=True)
        if not cached.exists():
            shutil.move(str(produced), str(cached))
        else:
            produced.unlink()
        return True
    except OSError:
        return False


def _patch_legacy_science_imports() -> None:
    if not hasattr(np, "int"):
        np.int = int  # type: ignore[attr-defined]
    if not hasattr(np, "float"):
        np.float = float  # type: ignore[attr-defined]
    if not hasattr(np, "complex"):
        np.complex = complex  # type: ignore[attr-defined]

    import scipy.integrate as integrate

    if not hasattr(integrate, "trapz"):
        integrate.trapz = np.trapz  # type: ignore[attr-defined]


def parse_tess_sector(product_uri: str | None) -> int | None:
    if not product_uri:
        return None
    match = re.search(r"(?:^|[-_/])[sS](\d{4})(?:[-_/.]|$)", product_uri)
    return int(match.group(1)) if match else None


def parse_tic_from_product_uri(product_uri: str | None) -> int | None:
    """Recover the TIC id from a TESS product URI.

    Name-based searches (e.g. "L 98-59") resolve products whose URIs embed the
    zero-padded TIC (SPOC: ``...-0000000307210830-...``, HLSP TESS-SPOC:
    ``..._0000000307210830-s0008_...``); without this fallback TRICERATOPS
    would be unavailable for every target the user typed by name.
    """
    if not product_uri:
        return None
    match = re.search(r"[-_](\d{13,16})[-_]", product_uri)
    if match:
        return int(match.group(1))
    return None


def _phase_time(time: np.ndarray, candidate: TransitCandidate) -> np.ndarray:
    return ((time - candidate.epoch + 0.5 * candidate.period) % candidate.period) - 0.5 * candidate.period


def _bin_for_triceratops(
    phase_time: np.ndarray,
    flux: np.ndarray,
    bins: int = 100,
) -> tuple[np.ndarray, np.ndarray, float]:
    finite = np.isfinite(phase_time) & np.isfinite(flux)
    x = np.asarray(phase_time[finite], dtype=np.float64)
    y = np.asarray(flux[finite], dtype=np.float64)
    if x.size < 16:
        raise ValueError("TRICERATOPS requires at least 16 finite folded cadences")
    order = np.argsort(x)
    x = x[order]
    y = y[order]
    edges = np.linspace(float(np.nanmin(x)), float(np.nanmax(x)), bins + 1)
    binned_time = []
    binned_flux = []
    for left, right in zip(edges[:-1], edges[1:], strict=True):
        mask = (x >= left) & (x < right)
        if not np.count_nonzero(mask):
            continue
        binned_time.append(float(np.nanmedian(x[mask])))
        binned_flux.append(float(np.nanmedian(y[mask])))
    residual = y - float(np.nanmedian(y))
    flux_err = float(np.nanstd(residual))
    if not np.isfinite(flux_err) or flux_err <= 0:
        raise ValueError("TRICERATOPS flux error estimate is invalid")
    return np.asarray(binned_time), np.asarray(binned_flux), flux_err


def _aperture_pixels(aperture_mask: np.ndarray | None) -> np.ndarray | None:
    if aperture_mask is None:
        return None
    mask = np.asarray(aperture_mask, dtype=bool)
    if mask.ndim != 2 or not mask.any():
        return None
    return np.argwhere(mask).astype(int)


def run_triceratops_fpp(
    *,
    target_id: str,
    product_uri: str | None,
    time: np.ndarray,
    flux: np.ndarray,
    candidate: TransitCandidate,
    aperture_mask: np.ndarray | None = None,
    samples: int = 1_000_000,
    parallel: bool = False,
) -> dict[str, Any]:
    _patch_legacy_science_imports()
    import triceratops.triceratops as tr

    tic_id = parse_tic_id(target_id)
    if tic_id is None:
        tic_id = parse_tic_from_product_uri(product_uri)
    if tic_id is None:
        raise ValueError(
            f"TRICERATOPS requires a numeric TIC id; none found in target {target_id!r} or its product URI"
        )
    sector = parse_tess_sector(product_uri)
    if sector is None:
        raise ValueError("TRICERATOPS requires a TESS sector parsed from the selected product URI")

    folded_time = _phase_time(np.asarray(time, dtype=np.float64), candidate)
    binned_time, binned_flux, flux_err = _bin_for_triceratops(folded_time, np.asarray(flux, dtype=np.float64))
    cached_trilegal = _cached_trilegal_path(tic_id)
    trilegal_fname = str(cached_trilegal) if cached_trilegal.exists() else None
    trilegal_source = "cached_file" if trilegal_fname else "live_query"
    ca_bundle = ensure_trilegal_ca_bundle() if trilegal_fname is None else None
    with _repaired_ca_environment(ca_bundle):
        if trilegal_fname is not None:
            try:
                target = tr.target(
                    ID=tic_id, sectors=np.asarray([sector], dtype=int), trilegal_fname=trilegal_fname
                )
            except TypeError:
                # Older/stubbed target signatures without trilegal_fname.
                target = tr.target(ID=tic_id, sectors=np.asarray([sector], dtype=int))
                trilegal_source = "live_query"
        else:
            target = tr.target(ID=tic_id, sectors=np.asarray([sector], dtype=int))
        aperture_pixels = _aperture_pixels(aperture_mask)
        calc_depths_used = False
        calc_depths_mode = None
        calc_depths_detail = None
        if hasattr(target, "calc_depths"):
            # calc_depths is mandatory before calc_probs (it populates the
            # per-star "tdepth" column). The selected TPF aperture lives in
            # TPF-relative pixel coordinates while TRICERATOPS expects its
            # own TessCut frame, so passing it directly mislocates (or
            # crashes) the per-star depth calculation; until WCS plumbing
            # converts frames, use TRICERATOPS' validated default aperture
            # (5x5 centered on the target in its own frame).
            try:
                target.calc_depths(tdepth=float(candidate.depth))
                calc_depths_used = True
                calc_depths_mode = "triceratops_default_5x5"
            except (TypeError, ValueError, RuntimeError, AttributeError, IndexError, KeyError) as exc:
                calc_depths_detail = str(exc)
        calc_probs_kwargs = {
            "time": binned_time,
            "flux_0": binned_flux,
            "flux_err_0": flux_err,
            "P_orb": float(candidate.period),
            "N": int(samples),
            "verbose": 0,
        }
        parallel_used = parallel
        try:
            target.calc_probs(**calc_probs_kwargs, parallel=parallel_used)
        except IndexError:
            # TRICERATOPS' scalar and vectorized Monte Carlo paths can hit
            # different degenerate-draw edge cases. Retry the supported
            # alternate path before declaring required FPP evidence missing.
            parallel_used = not parallel_used
            target.calc_probs(**calc_probs_kwargs, parallel=parallel_used)
    if trilegal_source == "live_query" and not _harvest_trilegal_result(tic_id):
        trilegal_source = "unavailable_scenarios_reduced"
    probs = getattr(target, "probs", None)
    probabilities = probs.to_dict(orient="records") if hasattr(probs, "to_dict") else None
    fpp = float(target.FPP)
    nfpp = float(target.NFPP)
    if not np.isfinite(fpp) or not np.isfinite(nfpp):
        raise RuntimeError("TRICERATOPS returned non-finite FPP/NFPP; evidence is unusable")
    return {
        "status": "complete",
        "engine": "triceratops",
        "target_id": tic_id,
        "sector": sector,
        "fpp": fpp,
        "nfpp": nfpp,
        "samples": int(samples),
        "parallel": parallel_used,
        "fpp_uncertainty": None,
        "nfpp_uncertainty": None,
        "aperture_available": aperture_pixels is not None,
        "aperture_used": False,
        "aperture_pixel_count": int(aperture_pixels.shape[0]) if aperture_pixels is not None else 0,
        "calc_depths_used": calc_depths_used,
        "calc_depths_mode": calc_depths_mode,
        "calc_depths_detail": calc_depths_detail,
        "trilegal_source": trilegal_source,
        "ca_bundle_used": ca_bundle is not None,
        "contrast_curve_used": False,
        "flux_err": flux_err,
        "probabilities": probabilities,
        "scenario_probabilities": probabilities,
        "validation_thresholds": {"fpp_max": 0.015, "nfpp_max": 0.001},
        "source": "TRICERATOPS calc_depths + calc_probs" if calc_depths_used else "TRICERATOPS calc_probs",
    }
