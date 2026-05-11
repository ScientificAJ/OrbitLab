from __future__ import annotations

from dataclasses import asdict
import numpy as np

from orbitlab.ml.astronet_adapter import build_astronet_tensors
from orbitlab.ml.nigraha_adapter import build_nigraha_tensors
from orbitlab.ml.nigraha_service import NigrahaService
from orbitlab.ml.exomac_service import ExoMACService, build_exomac_features
from orbitlab.ml.service import AstroNetService, KeplerAstroNetService
from orbitlab.science.bls import find_multi_planet_candidates, run_bls
from orbitlab.science.data_quality import clean_light_curve
from orbitlab.science.folding import bin_phase_curve, phase_fold
from orbitlab.science.physics import infer_planet_physics
from orbitlab.science.validation import validate_candidate


def analyze_light_curve_arrays(
    *,
    target_id: str,
    mission: str,
    time: np.ndarray,
    flux: np.ndarray,
    quality: np.ndarray | None = None,
    stellar_radius_solar: float | None = None,
    stellar_mass_solar: float | None = None,
    stellar_teff: float | None = None,
    stellar_logg: float | None = None,
    stellar_luminosity_solar: float | None = None,
    stellar_density_solar: float | None = None,
    max_candidates: int = 4,
    ml_service: AstroNetService | None = None,
    nigraha_service: NigrahaService | None = None,
    k2_service: ExoMACService | None = None,
) -> dict:
    clean_time, clean_flux = clean_light_curve(time, flux, quality)
    primary, periodogram = run_bls(clean_time, clean_flux)
    candidates = find_multi_planet_candidates(clean_time, clean_flux, max_candidates=max_candidates, initial_candidate=primary)

    folded_curves: dict[str, dict[str, list[float]]] = {}
    candidate_payloads = []
    mission_upper = mission.upper()
    service = ml_service
    tess_service = nigraha_service
    if mission_upper == "TESS" and tess_service is None:
        tess_service = NigrahaService()
    if mission_upper == "KEPLER" and service is None:
        service = KeplerAstroNetService()
    if mission_upper == "K2" and k2_service is None:
        k2_service = ExoMACService()
    for index, candidate in enumerate(candidates, start=1):
        candidate_id = f"{mission.lower()}-{target_id}-{index}"
        phase, folded_flux = phase_fold(clean_time, clean_flux, candidate.period, candidate.epoch)
        binned_phase, binned_flux = bin_phase_curve(phase, folded_flux, 401)
        folded_curves[candidate_id] = {
            "phase": binned_phase.astype(float).tolist(),
            "flux": binned_flux.astype(float).tolist(),
        }
        physics = None
        if stellar_radius_solar and stellar_mass_solar:
            physics = asdict(
                infer_planet_physics(
                    depth=candidate.depth,
                    period_days=candidate.period,
                    stellar_radius_solar=stellar_radius_solar,
                    stellar_mass_solar=stellar_mass_solar,
                    stellar_teff=stellar_teff,
                )
            )
        validation = asdict(validate_candidate(clean_time, clean_flux, candidate))
        if mission_upper == "TESS":
            tensors = build_nigraha_tensors(
                clean_time,
                clean_flux,
                candidate,
                stellar_teff=stellar_teff,
                stellar_radius_solar=stellar_radius_solar,
                stellar_logg=stellar_logg,
                stellar_mass_solar=stellar_mass_solar,
                stellar_luminosity_solar=stellar_luminosity_solar,
                stellar_density_solar=stellar_density_solar,
            )
            ml = asdict(tess_service.predict(tensors))
        elif mission_upper == "KEPLER":
            tensors = build_astronet_tensors(
                clean_time,
                clean_flux,
                candidate,
                stellar_radius_solar=stellar_radius_solar,
                stellar_mass_solar=stellar_mass_solar,
            )
            ml = asdict(service.predict(tensors))
        elif mission_upper == "K2":
            exomac_features = build_exomac_features(
                candidate,
                stellar_radius_solar=stellar_radius_solar,
                stellar_mass_solar=stellar_mass_solar,
                stellar_teff=stellar_teff,
                stellar_logg=stellar_logg,
                planet_radius_earth=physics.get("planet_radius_earth") if physics else None,
                semi_major_axis_au=physics.get("semi_major_axis_au") if physics else None,
            )
            ml = asdict(k2_service.predict(exomac_features))
        else:
            raise ValueError(f"unsupported mission: {mission}")
        candidate_payloads.append(
            {
                "candidate_id": candidate_id,
                "period": candidate.period,
                "epoch": candidate.epoch,
                "duration": candidate.duration,
                "depth": candidate.depth,
                "signal_to_noise": candidate.signal_to_noise,
                "physics": physics,
                "validation": validation,
                "ml": ml,
            }
        )

    return {
        "target_id": target_id,
        "mission": mission,
        "candidates": candidate_payloads,
        "periodogram": {
            "period": periodogram["period"].astype(float).tolist(),
            "power": periodogram["power"].astype(float).tolist(),
        },
        "folded_curves": folded_curves,
        "light_curve": {
            "time": clean_time.astype(float).tolist(),
            "flux": clean_flux.astype(float).tolist(),
        },
    }
