from __future__ import annotations

import json
import logging
from uuid import uuid4

import numpy as np

from orbitlab.config import settings

try:
    from celery import Celery
except ImportError as exc:  # pragma: no cover - optional worker install
    raise RuntimeError("Install orbitlab[api,science,ml] to run Celery workers") from exc

from orbitlab.science.data_quality import apply_manual_jitter_mask, clean_light_curve
from orbitlab.science.mast import extract_light_curve_bundle_from_tpf
from orbitlab.science.pipeline import analyze_light_curve_arrays
from orbitlab.storage.database import SessionLocal
from orbitlab.storage.json_safety import to_jsonable
from orbitlab.storage.orm import AnalysisJobRecord, AnalysisResultRecord, ApertureMaskRecord, ArtifactMaskRecord

logger = logging.getLogger(__name__)

celery_app = Celery("orbitlab", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.task_routes = {"orbitlab.worker.run_analysis_job": {"queue": "analysis"}}


@celery_app.task(name="orbitlab.worker.run_analysis_job", bind=True)
def run_analysis_job(self, job_id: str) -> str:
    logger.info("Starting analysis job: %s", job_id)
    with SessionLocal() as db:
        job = db.get(AnalysisJobRecord, job_id)
        if job is None:
            logger.error("Analysis job not found: %s", job_id)
            raise ValueError(f"analysis job not found: {job_id}")
        job.status = "running"
        job.error = None
        db.commit()
        try:
            aperture_mask = "pipeline"
            if job.aperture_mask_id:
                record = db.get(ApertureMaskRecord, job.aperture_mask_id)
                if record is None:
                    raise ValueError(f"aperture mask not found: {job.aperture_mask_id}")
                aperture_mask = json.loads(record.mask_json) if isinstance(record.mask_json, str) else record.mask_json
            logger.info("Extracting light curve for job: %s", job_id)
            bundle = extract_light_curve_bundle_from_tpf(job.product_uri, aperture_mask=aperture_mask)
            time, flux, quality = bundle.time, bundle.flux, bundle.quality
            diagnostic_pixel_flux = bundle.pixel_flux

            if job.artifact_mask_id:
                record = db.get(ArtifactMaskRecord, job.artifact_mask_id)
                if record is None:
                    raise ValueError(f"artifact mask not found: {job.artifact_mask_id}")

                indices = (
                    json.loads(record.indices_json) if isinstance(record.indices_json, str) else record.indices_json
                )

                clean_time, clean_flux = clean_light_curve(time, flux, quality)

                mask = np.zeros(clean_time.shape, dtype=bool)
                index_array = np.asarray(indices, dtype=int)

                if index_array.size and (index_array.min() < 0 or index_array.max() >= mask.size):
                    raise ValueError("artifact mask indices are outside the cleaned light curve cadence range")

                mask[index_array] = True
                time, flux, _ = apply_manual_jitter_mask(clean_time, clean_flux, mask, reason=record.reason)
                quality = None
                diagnostic_pixel_flux = None

            logger.info("Analyzing light curve arrays for job: %s", job_id)
            payload = analyze_light_curve_arrays(
                target_id=job.target_id,
                mission=job.mission,
                product_uri=job.product_uri,
                time=time,
                flux=flux,
                quality=quality,
                stellar_radius_solar=float(job.stellar_radius_solar) if job.stellar_radius_solar else None,
                stellar_mass_solar=float(job.stellar_mass_solar) if job.stellar_mass_solar else None,
                stellar_teff=float(job.stellar_teff) if job.stellar_teff else None,
                stellar_logg=float(job.stellar_logg) if job.stellar_logg else None,
                stellar_luminosity_solar=float(job.stellar_luminosity_solar) if job.stellar_luminosity_solar else None,
                stellar_density_solar=float(job.stellar_density_solar) if job.stellar_density_solar else None,
                stellar_rotation_period=float(job.stellar_rotation_period) if job.stellar_rotation_period else None,
                request_min_period=float(job.min_period) if job.min_period else None,
                request_max_period=float(job.max_period) if job.max_period else None,
                max_candidates=job.max_candidates,
                vetting_mode=job.vetting_mode,
                pixel_flux=diagnostic_pixel_flux,
                aperture_mask=bundle.selected_mask,
                pixel_scale_arcsec=bundle.pixel_scale_arcsec,
                tpf_metadata={
                    "target_pixel_row": bundle.target_pixel_row,
                    "target_pixel_col": bundle.target_pixel_col,
                    "target_ra": bundle.target_ra,
                    "target_dec": bundle.target_dec,
                    "wcs_pixel_scale_matrix": bundle.wcs_pixel_scale_matrix,
                    "mission_name": bundle.mission_name,
                    "kepler_channel": bundle.kepler_channel,
                    "tess_camera": bundle.tess_camera,
                    "tess_ccd": bundle.tess_ccd,
                    "tess_sector": bundle.tess_sector,
                },
            )
            result_id = str(uuid4())
            payload["result_id"] = result_id
            payload = to_jsonable(payload)
            db.add(AnalysisResultRecord(id=result_id, job_id=job.id, payload_json=payload))
            job.status = "complete"
            job.error = None
            db.commit()
            logger.info("Successfully completed analysis job: %s", job_id)
            return result_id
        except json.JSONDecodeError as exc:
            db.rollback()
            logger.error("JSONDecodeError in job %s: %s", job_id, exc)
            job.status = "failed"
            job.error = str(exc)
            db.commit()
            raise
        except ValueError as exc:
            db.rollback()
            logger.error("ValueError in job %s: %s", job_id, exc)
            job.status = "failed"
            job.error = str(exc)
            db.commit()
            raise
        except Exception as exc:
            db.rollback()
            logger.error("Exception in job %s: %s", job_id, exc, exc_info=True)
            job.status = "failed"
            job.error = str(exc)
            db.commit()
            raise
