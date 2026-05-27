from uuid import uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from orbitlab.api.main import app
from orbitlab.api.schemas import AnalysisJobCreate
from orbitlab.storage.database import SessionLocal, init_db
from orbitlab.storage.orm import AnalysisJobRecord, AnalysisResultRecord

# init_db() here to ensure the migration runs in the test process
init_db()


def test_get_analysis_result_handles_json_dict():
    with TestClient(app) as client:
        db = SessionLocal()
        job_id = str(uuid4())
        result_id = str(uuid4())

        # Mock job
        job = AnalysisJobRecord(id=job_id, target_id="test", product_uri="test", mission="TESS", status="complete")
        db.add(job)
        db.commit()

        # Mock result with full valid dict
        payload = {
            "result_id": result_id,
            "target_id": "test",
            "mission": "TESS",
            "candidates": [],
            "periodogram": {"period": [], "power": []},
            "folded_curves": {},
            "light_curve": {"time": [], "flux": []},
        }
        record = AnalysisResultRecord(id=result_id, job_id=job_id, payload_json=payload)
        db.add(record)
        db.commit()

        response = client.get(f"/api/v1/analysis-results/{result_id}")
        assert response.status_code == 200
        assert response.json()["target_id"] == "test"
        assert response.json()["result_id"] == result_id
        db.close()


def test_bls_preview_missing_aperture_returns_404():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/bls-preview",
            json={
                "product_uri": "mast:test",
                "mission": "TESS",
                "aperture_mask_id": "missing-uuid",
            },
        )
        assert response.status_code == 404
        assert "aperture mask not found" in response.json()["detail"]


def test_bls_preview_preserves_reviewable_primary_tce(monkeypatch):
    from orbitlab.science.bls import TransitCandidate

    candidate = TransitCandidate(2.15, 0.35, 0.11, 0.0018, 12.0, 4.8)
    time = np.linspace(0, 27, 300, dtype=np.float32)
    flux = (1.0 + 0.001 * np.sin(time)).astype(np.float32)

    class _BlsResult:
        periodogram = {
            "period": np.array([candidate.period], dtype=np.float32),
            "power": np.array([candidate.power], dtype=np.float32),
            "duration": np.array([candidate.duration], dtype=np.float32),
        }
        search_time = time
        search_flux = flux
        clean_time = time
        clean_flux = flux
        metadata = {"min_period_days": 0.5, "max_period_days": 10.0}

        def __init__(self):
            self.candidate = candidate

    monkeypatch.setattr("orbitlab.api.main.extract_light_curve_from_tpf", lambda *args, **kwargs: (time, flux, None))
    monkeypatch.setattr("orbitlab.api.main.run_bls", lambda *args, **kwargs: _BlsResult())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/bls-preview",
            json={
                "product_uri": "mast:test",
                "mission": "TESS",
                "max_candidates": 1,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidates"][0]["period"] == pytest.approx(candidate.period)
    assert payload["candidates"][0]["signal_to_noise"] == pytest.approx(candidate.signal_to_noise)


def test_bls_preview_rejects_invalid_period_range():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/bls-preview",
            json={
                "product_uri": "mast:test",
                "mission": "TESS",
                "min_period": 30.0,
                "max_period": 0.5,
            },
        )
        assert response.status_code == 422  # Pydantic validation error


def test_model_status_uses_exomac_for_k2_surface():
    with TestClient(app) as client:
        response = client.get("/api/v1/models")
        assert response.status_code == 200
        payload = response.json()
        assert "k2_exomac_kkt" in payload
        assert "k2_astronet" not in payload


def test_aperture_mask_rejects_empty_selection():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/aperture-masks",
            json={
                "target_id": "test",
                "product_uri": "mast:test",
                "mask": [[False, False], [False, False]],
                "reason": "empty test mask",
            },
        )
        assert response.status_code == 422
        assert "aperture mask must select at least one pixel" in response.text


def test_aperture_mask_rejects_ragged_grid():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/aperture-masks",
            json={
                "target_id": "test",
                "product_uri": "mast:test",
                "mask": [[True], [False, True]],
                "reason": "ragged test mask",
            },
        )
        assert response.status_code == 422
        assert "aperture mask rows must all have the same length" in response.text


def test_analysis_job_accepts_artifact_mask_id():
    with TestClient(app) as client:
        # We won't run it, just check creation
        response = client.post(
            "/api/v1/analysis-jobs",
            json={"target_id": "test", "product_uri": "test", "mission": "TESS", "artifact_mask_id": "non-existent"},
        )
        # Should 404 because it checks existence
        assert response.status_code == 404
        assert "artifact mask not found" in response.json()["detail"]


def test_health_reports_database_and_worker_mode():
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["api"] == "ok"
    assert payload["database"] == "ok"
    assert payload["worker_mode"] in {"inline", "celery"}
    assert payload["frontend"] == "served separately"


def test_analysis_job_schema_accepts_richer_stellar_context():
    payload = AnalysisJobCreate(
        target_id="test",
        product_uri="test",
        mission="TESS",
        stellar_radius_solar=1.0,
        stellar_mass_solar=1.0,
        stellar_teff=5778,
        stellar_logg=4.44,
        stellar_luminosity_solar=1.0,
        stellar_density_solar=1.0,
        stellar_rotation_period=25.0,
        vetting_mode="deep",
    )

    assert payload.stellar_teff == 5778
    assert payload.stellar_rotation_period == 25.0
    assert payload.vetting_mode == "deep"


def test_analysis_job_schema_accepts_paper_grade_vetting_mode():
    payload = AnalysisJobCreate(
        target_id="test",
        product_uri="test",
        mission="TESS",
        vetting_mode="paper",
    )

    assert payload.vetting_mode == "paper"
