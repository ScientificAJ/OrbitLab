from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import uuid4

try:
    from fastapi import FastAPI, HTTPException, Query, Depends
    from fastapi.middleware.cors import CORSMiddleware
    from sqlalchemy.orm import Session
except ImportError as exc:  # pragma: no cover - import guard for minimal environments
    raise RuntimeError("Install orbitlab[api] to run the FastAPI application") from exc

from orbitlab.api.schemas import (
    AnalysisJob,
    AnalysisJobCreate,
    AnalysisResult,
    ApertureMaskCreate,
    ApertureMaskResponse,
    ArtifactMaskResponse,
    BlsPreviewCreate,
    JobStatus,
    MaskCreate,
    Product,
    ReportResponse,
    SearchResult,
    SavedSession,
    SavedSessionCreate,
)
from orbitlab.config import settings
from orbitlab.exceptions import ModelArtifactError
from orbitlab.ml.artifact_registry import K2_ASTRONET_MODEL_ID, K2_EXOMAC_MODEL_ID, KEPLER_ASTRONET_MODEL_ID, artifact_status
from orbitlab.ml.exomac_service import ExoMACService
from orbitlab.ml.nigraha_service import NigrahaService
from orbitlab.ml.service import KeplerAstroNetService
from orbitlab.science.bls import find_multi_planet_candidates, run_bls
from orbitlab.science.data_quality import clean_light_curve
from orbitlab.science.mast import extract_light_curve_from_tpf, list_tpf_products, resolve_tpf_path, search_targets
from orbitlab.storage.database import SessionLocal, init_db
from orbitlab.storage.orm import (
    AnalysisJobRecord,
    AnalysisResultRecord,
    ApertureMaskRecord,
    ArtifactMaskRecord,
    SavedSessionRecord,
)
from orbitlab.worker import celery_app, run_analysis_job


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="OrbitLab API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _job_payload(record: AnalysisJobRecord) -> AnalysisJob:
    result_id = record.result.id if record.result else None
    return AnalysisJob(
        job_id=record.id,
        status=JobStatus(record.status),
        created_at=record.created_at,
        result_id=result_id,
        error=record.error,
    )


@app.get(f"{settings.api_prefix}/search", response_model=list[SearchResult])
def search(query: str = Query(min_length=1), mission: str | None = None):
    try:
        return search_targets(query, mission=mission)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get(f"{settings.api_prefix}/targets/{{target_id}}/products", response_model=list[Product])
def products(target_id: str, mission: str | None = None):
    try:
        return list_tpf_products(target_id, mission=mission)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get(f"{settings.api_prefix}/tpf-preview")
def tpf_preview(product_uri: str):
    try:
        import lightkurve as lk
        import numpy as np

        path = resolve_tpf_path(product_uri)
        tpf = lk.read(str(path))
        image = np.nanmedian(np.asarray(tpf.flux.value, dtype=float), axis=0)
        return {
            "shape": list(image.shape),
            "image": image.tolist(),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post(f"{settings.api_prefix}/bls-preview")
def bls_preview(payload: BlsPreviewCreate, db: Session = Depends(get_db)):
    try:
        from orbitlab.science.folding import bin_phase_curve, phase_fold

        aperture_mask = "pipeline"
        if payload.aperture_mask_id:
            record = db.get(ApertureMaskRecord, payload.aperture_mask_id)
            if record is None:
                raise HTTPException(status_code=404, detail="aperture mask not found")
            aperture_mask = record.mask_json
        time, flux, quality = extract_light_curve_from_tpf(payload.product_uri, aperture_mask=aperture_mask)
        clean_time, clean_flux = clean_light_curve(time, flux, quality)
        bls_result = run_bls(
            clean_time,
            clean_flux,
            min_period=payload.min_period,
            max_period=payload.max_period,
            period_samples=4096,
        )
        candidate = bls_result.candidate
        periodogram = bls_result.periodogram

        candidates = find_multi_planet_candidates(
            clean_time,
            clean_flux,
            max_candidates=payload.max_candidates,
            initial_candidate=candidate,
            min_period=payload.min_period,
            max_period=payload.max_period,
            period_samples=4096,
        )

        folded_curves = {}
        for index, c in enumerate(candidates, start=1):
            candidate_id = f"preview-{index}"
            phase, folded_flux = phase_fold(bls_result.search_time, bls_result.search_flux, c.period, c.epoch)
            binned_phase, binned_flux = bin_phase_curve(phase, folded_flux, 401)
            folded_curves[candidate_id] = {
                "phase": binned_phase.astype(float).tolist(),
                "flux": binned_flux.astype(float).tolist(),
            }

        return {
            "periodogram": {
                "period": periodogram["period"].astype(float).tolist(),
                "power": periodogram["power"].astype(float).tolist(),
                "duration": periodogram["duration"].astype(float).tolist(),
            },
            "candidates": [
                {
                    "candidate_id": f"preview-{i}",
                    "period": c.period,
                    "epoch": c.epoch,
                    "duration": c.duration,
                    "depth": c.depth,
                    "signal_to_noise": c.signal_to_noise,
                }
                for i, c in enumerate(candidates, start=1)
            ],
            "folded_curves": folded_curves,
            "bls_light_curve": {
                "time": bls_result.search_time.astype(float).tolist(),
                "flux": bls_result.search_flux.astype(float).tolist(),
            },
            "preprocessing": bls_result.metadata,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post(f"{settings.api_prefix}/analysis-jobs", response_model=AnalysisJob, status_code=201)
async def create_analysis_job(payload: AnalysisJobCreate, db: Session = Depends(get_db)):
    job_id = str(uuid4())
    record = AnalysisJobRecord(
        id=job_id,
        target_id=payload.target_id,
        product_uri=payload.product_uri,
        mission=payload.mission,
        aperture_mask_id=payload.aperture_mask_id,
        artifact_mask_id=payload.artifact_mask_id,
        max_candidates=payload.max_candidates,
        stellar_radius_solar=payload.stellar_radius_solar,
        stellar_mass_solar=payload.stellar_mass_solar,
        status=JobStatus.queued.value,
    )
    if payload.aperture_mask_id and db.get(ApertureMaskRecord, payload.aperture_mask_id) is None:
        raise HTTPException(status_code=404, detail="aperture mask not found")
    if payload.artifact_mask_id and db.get(ArtifactMaskRecord, payload.artifact_mask_id) is None:
        raise HTTPException(status_code=404, detail="artifact mask not found")
    db.add(record)
    db.commit()
    inline_errors: list[str] = []
    if settings.run_jobs_inline:
        try:
            await asyncio.to_thread(run_analysis_job, job_id)
        except Exception as exc:
            inline_errors.append(str(exc) or exc.__class__.__name__)
    else:
        celery_app.send_task("orbitlab.worker.run_analysis_job", args=[job_id])
    stored = db.get(AnalysisJobRecord, job_id)
    if stored is None:
        raise HTTPException(status_code=500, detail="job record disappeared")
    if inline_errors and stored.status != JobStatus.failed.value:
        stored.status = JobStatus.failed.value
        stored.error = inline_errors[-1]
        db.commit()
        db.refresh(stored)
    return _job_payload(stored)


@app.get(f"{settings.api_prefix}/analysis-jobs/{{job_id}}", response_model=AnalysisJob)
def get_analysis_job(job_id: str, db: Session = Depends(get_db)):
    record = db.get(AnalysisJobRecord, job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_payload(record)


@app.get(f"{settings.api_prefix}/analysis-results/{{result_id}}", response_model=AnalysisResult)
def get_analysis_result(result_id: str, db: Session = Depends(get_db)):
    record = db.get(AnalysisResultRecord, result_id)
    if record is None:
        raise HTTPException(status_code=404, detail="result not found")
    return json.loads(record.payload_json) if isinstance(record.payload_json, str) else record.payload_json


@app.post(f"{settings.api_prefix}/artifact-masks", response_model=ArtifactMaskResponse, status_code=201)
def create_artifact_mask(payload: MaskCreate, db: Session = Depends(get_db)):
    record = ArtifactMaskRecord(
        id=str(uuid4()),
        target_id=payload.target_id,
        indices_json=payload.indices,
        reason=payload.reason,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {
        "mask_id": record.id,
        "target_id": record.target_id,
        "indices": record.indices_json,
        "reason": record.reason,
        "created_at": record.created_at.isoformat(),
    }


@app.post(f"{settings.api_prefix}/aperture-masks", response_model=ApertureMaskResponse, status_code=201)
def create_aperture_mask(payload: ApertureMaskCreate, db: Session = Depends(get_db)):
    record = ApertureMaskRecord(
        id=str(uuid4()),
        target_id=payload.target_id,
        product_uri=payload.product_uri,
        mask_json=payload.mask,
        reason=payload.reason,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    mask = json.loads(record.mask_json) if isinstance(record.mask_json, str) else record.mask_json
    return {
        "aperture_mask_id": record.id,
        "target_id": record.target_id,
        "product_uri": record.product_uri,
        "mask": mask,
        "reason": record.reason,
        "created_at": record.created_at.isoformat(),
    }


@app.get(f"{settings.api_prefix}/models", response_model=dict[str, Any])
def model_status():
    statuses = {}
    try:
        statuses["nigraha_tess"] = NigrahaService().validate_artifact().__dict__
    except (ModelArtifactError, KeyError, FileNotFoundError) as exc:
        statuses["nigraha_tess"] = {"status": "unavailable", "detail": str(exc)}
    statuses["kepler_astronet"] = artifact_status(KEPLER_ASTRONET_MODEL_ID)
    try:
        statuses["kepler_astronet"] = KeplerAstroNetService().validate_artifact().__dict__
    except (ModelArtifactError, KeyError, FileNotFoundError) as exc:
        statuses["kepler_astronet"] = statuses["kepler_astronet"] | {"status": "unavailable", "detail": str(exc)}
    statuses["k2_astronet"] = artifact_status(K2_ASTRONET_MODEL_ID)
    statuses["k2_exomac_kkt"] = artifact_status(K2_EXOMAC_MODEL_ID)
    try:
        statuses["k2_exomac_kkt"] = ExoMACService().validate_artifact().__dict__
    except (ModelArtifactError, KeyError, FileNotFoundError) as exc:
        statuses["k2_exomac_kkt"] = statuses["k2_exomac_kkt"] | {"status": "unavailable", "detail": str(exc)}
    return statuses


@app.get(f"{settings.api_prefix}/sessions", response_model=list[SavedSession])
def list_sessions(db: Session = Depends(get_db)):
    records = db.query(SavedSessionRecord).order_by(SavedSessionRecord.created_at.desc()).all()
    return [
        SavedSession(
            session_id=record.id,
            name=record.name,
            payload=record.payload_json,
            created_at=record.created_at,
        )
        for record in records
    ]


@app.post(f"{settings.api_prefix}/sessions", response_model=SavedSession, status_code=201)
def save_session(payload: SavedSessionCreate, db: Session = Depends(get_db)):
    record = SavedSessionRecord(
        id=str(uuid4()),
        name=payload.name,
        payload_json=payload.payload,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return SavedSession(
        session_id=record.id,
        name=record.name,
        payload=record.payload_json,
        created_at=record.created_at,
    )


@app.get(f"{settings.api_prefix}/reports/{{report_id}}", response_model=ReportResponse)
def report(report_id: str, db: Session = Depends(get_db)):
    record = db.get(AnalysisResultRecord, report_id)
    if record is None:
        raise HTTPException(status_code=404, detail="report not found")
    from datetime import timezone

    return {
        "report_id": report_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "format": "json",
        "result": json.loads(record.payload_json) if isinstance(record.payload_json, str) else record.payload_json,
    }
