from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from orbitlab.api.main import app
from orbitlab.storage.database import SessionLocal, init_db
from orbitlab.storage.orm import (
    AnalysisJobRecord,
    AnalysisResultRecord,
    ApertureMaskRecord,
    ArtifactMaskRecord,
    SavedSessionRecord,
)

init_db()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# POST /analysis-jobs — creation paths
# ---------------------------------------------------------------------------
def test_create_analysis_job_returns_201_and_queued_status(client, monkeypatch):
    # Patch the celery send_task so the job is accepted without a real broker.
    # The default test environment has run_jobs_inline=True so the inline path runs;
    # patch run_analysis_job to be a no-op to avoid actual TPF work.
    monkeypatch.setattr("orbitlab.api.main.run_analysis_job", lambda job_id: None)
    response = client.post(
        "/api/v1/analysis-jobs",
        json={"target_id": "TIC 100", "product_uri": "mast:test", "mission": "TESS"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "queued"
    assert "job_id" in data


def test_create_analysis_job_rejects_missing_aperture_mask(client):
    response = client.post(
        "/api/v1/analysis-jobs",
        json={
            "target_id": "TIC 100",
            "product_uri": "mast:test",
            "mission": "TESS",
            "aperture_mask_id": str(uuid4()),
        },
    )
    assert response.status_code == 404
    assert "aperture mask not found" in response.json()["detail"]


def test_create_analysis_job_rejects_aperture_mask_wrong_target(client):
    with SessionLocal() as db:
        mask = ApertureMaskRecord(
            id=str(uuid4()),
            target_id="TIC 999",
            product_uri="mast:different-product",
            mask_json=[[True]],
            reason="mismatch test",
        )
        db.add(mask)
        db.commit()
        mask_id = mask.id

    response = client.post(
        "/api/v1/analysis-jobs",
        json={
            "target_id": "TIC 100",
            "product_uri": "mast:test",
            "mission": "TESS",
            "aperture_mask_id": mask_id,
        },
    )
    assert response.status_code == 409
    assert "different target" in response.json()["detail"]


def test_create_analysis_job_rejects_artifact_mask_wrong_target(client):
    with SessionLocal() as db:
        artifact = ArtifactMaskRecord(
            id=str(uuid4()),
            target_id="TIC 999",
            indices_json=[0, 1],
            reason="wrong target",
        )
        db.add(artifact)
        db.commit()
        artifact_id = artifact.id

    response = client.post(
        "/api/v1/analysis-jobs",
        json={
            "target_id": "TIC 100",
            "product_uri": "mast:test",
            "mission": "TESS",
            "artifact_mask_id": artifact_id,
        },
    )
    assert response.status_code == 409
    assert "different target" in response.json()["detail"]


def test_create_analysis_job_includes_all_stellar_context_fields(client, monkeypatch):
    monkeypatch.setattr("orbitlab.api.main.run_analysis_job", lambda job_id: None)
    response = client.post(
        "/api/v1/analysis-jobs",
        json={
            "target_id": "TIC 200",
            "product_uri": "mast:test2",
            "mission": "TESS",
            "stellar_radius_solar": 1.1,
            "stellar_mass_solar": 0.95,
            "stellar_teff": 5600,
            "stellar_logg": 4.4,
            "stellar_luminosity_solar": 0.9,
            "stellar_density_solar": 1.2,
            "stellar_rotation_period": 22.0,
            "vetting_mode": "paper",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "queued"


# ---------------------------------------------------------------------------
# GET /analysis-jobs/{job_id}
# ---------------------------------------------------------------------------
def test_get_analysis_job_returns_404_for_missing(client):
    response = client.get(f"/api/v1/analysis-jobs/{uuid4()}")
    assert response.status_code == 404
    assert "job not found" in response.json()["detail"]


def test_get_analysis_job_returns_status_for_existing(client):
    with SessionLocal() as db:
        job = AnalysisJobRecord(
            id=str(uuid4()),
            target_id="TIC 333",
            product_uri="mast:test",
            mission="TESS",
            status="running",
        )
        db.add(job)
        db.commit()
        job_id = job.id

    response = client.get(f"/api/v1/analysis-jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert response.json()["job_id"] == job_id


# ---------------------------------------------------------------------------
# POST /artifact-masks — creation
# ---------------------------------------------------------------------------
def test_create_artifact_mask_returns_201(client):
    response = client.post(
        "/api/v1/artifact-masks",
        json={"target_id": "TIC 400", "indices": [5, 10, 15], "reason": "cosmic ray"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["target_id"] == "TIC 400"
    assert data["indices"] == [5, 10, 15]
    assert data["reason"] == "cosmic ray"
    assert "mask_id" in data
    assert "created_at" in data


def test_create_artifact_mask_persists_to_database(client):
    target = f"TIC {uuid4().int % 10000}"
    client.post(
        "/api/v1/artifact-masks",
        json={"target_id": target, "indices": [0, 1], "reason": "persistence check"},
    )
    with SessionLocal() as db:
        records = db.query(ArtifactMaskRecord).filter_by(target_id=target).all()
        assert len(records) == 1
        assert records[0].reason == "persistence check"


def test_create_artifact_mask_rejects_empty_indices(client):
    response = client.post(
        "/api/v1/artifact-masks",
        json={"target_id": "TIC 500", "indices": [], "reason": "empty mask"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /aperture-masks — creation
# ---------------------------------------------------------------------------
def test_create_aperture_mask_returns_201(client):
    response = client.post(
        "/api/v1/aperture-masks",
        json={
            "target_id": "TIC 600",
            "product_uri": "mast:product-x",
            "mask": [[True, False], [False, True]],
            "reason": "custom aperture",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["target_id"] == "TIC 600"
    assert "aperture_mask_id" in data
    assert data["mask"] == [[True, False], [False, True]]


def test_create_aperture_mask_round_trips_json_mask(client):
    mask = [[True, True, False], [False, True, False]]
    response = client.post(
        "/api/v1/aperture-masks",
        json={
            "target_id": "TIC 700",
            "product_uri": "mast:product-y",
            "mask": mask,
            "reason": "round trip test",
        },
    )
    assert response.status_code == 201
    assert response.json()["mask"] == mask


# ---------------------------------------------------------------------------
# GET /analysis-results/{result_id}
# ---------------------------------------------------------------------------
def test_get_analysis_result_returns_404_for_missing(client):
    response = client.get(f"/api/v1/analysis-results/{uuid4()}")
    assert response.status_code == 404
    assert "result not found" in response.json()["detail"]


def test_get_analysis_result_aliases_candidates_field(client):
    with SessionLocal() as db:
        job = AnalysisJobRecord(
            id=str(uuid4()),
            target_id="TIC 800",
            product_uri="mast:result-test",
            mission="TESS",
            status="complete",
        )
        db.add(job)
        result_id = str(uuid4())
        payload = {
            "result_id": result_id,
            "target_id": "TIC 800",
            "mission": "TESS",
            "planet_candidates": [],
            "tces": [],
            "periodogram": {"period": [], "power": []},
            "folded_curves": {},
            "light_curve": {"time": [], "flux": []},
        }
        result = AnalysisResultRecord(id=result_id, job_id=job.id, payload_json=payload)
        db.add(result)
        db.commit()

    response = client.get(f"/api/v1/analysis-results/{result_id}")
    assert response.status_code == 200
    data = response.json()
    assert "candidates" in data
    assert "planet_candidates" in data


# ---------------------------------------------------------------------------
# GET /reports/{report_id}
# ---------------------------------------------------------------------------
def test_get_report_returns_404_for_missing(client):
    response = client.get(f"/api/v1/reports/{uuid4()}")
    assert response.status_code == 404


def test_get_report_returns_result_payload(client):
    with SessionLocal() as db:
        job = AnalysisJobRecord(
            id=str(uuid4()),
            target_id="TIC 900",
            product_uri="mast:report-test",
            mission="TESS",
            status="complete",
        )
        db.add(job)
        result_id = str(uuid4())
        payload = {
            "result_id": result_id,
            "target_id": "TIC 900",
            "mission": "TESS",
            "planet_candidates": [],
            "tces": [],
            "periodogram": {"period": [], "power": []},
            "folded_curves": {},
            "light_curve": {"time": [], "flux": []},
        }
        result = AnalysisResultRecord(id=result_id, job_id=job.id, payload_json=payload)
        db.add(result)
        db.commit()

    response = client.get(f"/api/v1/reports/{result_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["report_id"] == result_id
    assert "generated_at" in data
    assert data["format"] == "json"
    assert data["result"]["target_id"] == "TIC 900"


# ---------------------------------------------------------------------------
# GET /sessions and POST /sessions
# ---------------------------------------------------------------------------
def test_save_and_list_sessions(client):
    session_payload = {"stars": ["TIC 100"], "mission": "TESS"}
    save_response = client.post(
        "/api/v1/sessions",
        json={"name": "My Session", "payload": session_payload},
    )
    assert save_response.status_code == 201
    saved = save_response.json()
    assert saved["name"] == "My Session"
    assert "session_id" in saved

    list_response = client.get("/api/v1/sessions")
    assert list_response.status_code == 200
    sessions = list_response.json()
    ids = [s["session_id"] for s in sessions]
    assert saved["session_id"] in ids


def test_save_session_preserves_arbitrary_payload(client):
    payload = {"nested": {"value": 42}, "list": [1, 2, 3]}
    response = client.post("/api/v1/sessions", json={"name": "Deep Payload", "payload": payload})
    assert response.status_code == 201
    assert response.json()["payload"] == payload


# ---------------------------------------------------------------------------
# GET /search — proxy error handling
# ---------------------------------------------------------------------------
def test_search_proxies_502_on_mast_failure(client, monkeypatch):
    monkeypatch.setattr(
        "orbitlab.api.main.search_targets",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("MAST down")),
    )
    response = client.get("/api/v1/search?query=TIC+100")
    assert response.status_code == 502


def test_search_returns_empty_list_for_no_matches(client, monkeypatch):
    monkeypatch.setattr("orbitlab.api.main.search_targets", lambda *a, **kw: [])
    response = client.get("/api/v1/search?query=TIC+100")
    assert response.status_code == 200
    assert response.json() == []


def test_search_rejects_empty_query(client):
    response = client.get("/api/v1/search?query=")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /targets/{target_id}/products
# ---------------------------------------------------------------------------
def test_products_returns_502_on_lightkurve_error(client, monkeypatch):
    monkeypatch.setattr(
        "orbitlab.api.main.list_tpf_products",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("lightkurve down")),
    )
    response = client.get("/api/v1/targets/TIC+100/products?mission=TESS")
    assert response.status_code == 502


def test_products_returns_empty_list_for_no_products(client, monkeypatch):
    monkeypatch.setattr("orbitlab.api.main.list_tpf_products", lambda *a, **kw: [])
    response = client.get("/api/v1/targets/TIC+100/products?mission=TESS")
    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------
def test_health_ok_when_db_reachable(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "ok"
    assert data["api"] == "ok"
    assert "generated_at" in data
