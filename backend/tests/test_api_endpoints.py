from __future__ import annotations

import sys
import types
from uuid import uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from orbitlab.api.main import app
from orbitlab.storage.database import SessionLocal, init_db
from orbitlab.storage.orm import (
    AnalysisJobRecord,
    AnalysisResultRecord,
    ApertureMaskRecord,
    ArtifactMaskRecord,
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


def test_create_analysis_job_rejects_missing_artifact_mask(client):
    response = client.post(
        "/api/v1/analysis-jobs",
        json={
            "target_id": "TIC 100",
            "product_uri": "mast:test",
            "mission": "TESS",
            "artifact_mask_id": str(uuid4()),
        },
    )
    assert response.status_code == 404
    assert "artifact mask not found" in response.json()["detail"]


def test_create_analysis_job_accepts_matching_aperture_and_artifact_masks(client, monkeypatch):
    monkeypatch.setattr("orbitlab.api.main.run_analysis_job", lambda job_id: None)
    with SessionLocal() as db:
        aperture = ApertureMaskRecord(
            id=str(uuid4()),
            target_id="TIC 100",
            product_uri="mast:test",
            mask_json=[[True]],
            reason="matching aperture",
        )
        artifact = ArtifactMaskRecord(
            id=str(uuid4()),
            target_id="TIC 100",
            indices_json=[0, 1],
            reason="matching artifact",
        )
        db.add_all([aperture, artifact])
        db.commit()
        aperture_id = aperture.id
        artifact_id = artifact.id

    response = client.post(
        "/api/v1/analysis-jobs",
        json={
            "target_id": "TIC 100",
            "product_uri": "mast:test",
            "mission": "TESS",
            "aperture_mask_id": aperture_id,
            "artifact_mask_id": artifact_id,
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "queued"


def test_create_analysis_job_dispatches_celery_when_inline_mode_disabled(client, monkeypatch):
    import orbitlab.api.main as api_main

    sent = {}

    class FakeCelery:
        def send_task(self, name, *, args):
            sent["name"] = name
            sent["args"] = args

    monkeypatch.setattr(api_main, "settings", api_main.replace(api_main.settings, run_jobs_inline=False))
    monkeypatch.setattr("orbitlab.api.main.celery_app", FakeCelery())

    response = client.post(
        "/api/v1/analysis-jobs",
        json={"target_id": "TIC 101", "product_uri": "mast:celery", "mission": "TESS"},
    )

    assert response.status_code == 201
    assert sent["name"] == "orbitlab.worker.run_analysis_job"
    assert sent["args"] == [response.json()["job_id"]]


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


def test_get_analysis_result_aliases_legacy_candidates_to_planet_candidates_and_tces(client):
    with SessionLocal() as db:
        job = AnalysisJobRecord(
            id=str(uuid4()),
            target_id="TIC 801",
            product_uri="mast:legacy-result-test",
            mission="TESS",
            status="complete",
        )
        db.add(job)
        result_id = str(uuid4())
        legacy_candidates = [
            {
                "candidate_id": "legacy",
                "period": 2.0,
                "epoch": 0.5,
                "duration": 0.1,
                "depth": 0.001,
                "signal_to_noise": 8.0,
            }
        ]
        payload = {
            "result_id": result_id,
            "target_id": "TIC 801",
            "mission": "TESS",
            "candidates": legacy_candidates,
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
    assert data["planet_candidates"][0]["candidate_id"] == "legacy"
    assert data["planet_candidates"][0]["period"] == 2.0
    assert data["tces"][0]["candidate_id"] == "legacy"
    assert data["tces"][0]["period"] == 2.0


# ---------------------------------------------------------------------------
# GET /tpf-preview
# ---------------------------------------------------------------------------
def test_tpf_preview_returns_image_and_baseline(client, monkeypatch):
    class FakeFlux:
        value = np.asarray(
            [
                [[1.0, np.nan], [3.0, 4.0]],
                [[2.0, 5.0], [np.nan, 8.0]],
            ],
            dtype=float,
        )

    class FakeTime:
        value = np.asarray([10.0, 12.5], dtype=float)

    fake_tpf = types.SimpleNamespace(flux=FakeFlux(), time=FakeTime())
    monkeypatch.setitem(sys.modules, "lightkurve", types.SimpleNamespace(read=lambda path: fake_tpf))
    monkeypatch.setattr("orbitlab.api.main.resolve_tpf_path", lambda product_uri: product_uri)

    response = client.get("/api/v1/tpf-preview?product_uri=mast:test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["shape"] == [2, 2]
    assert payload["baseline"] == pytest.approx(2.5)
    assert payload["finite_min"] == pytest.approx(1.5)
    assert payload["finite_max"] == pytest.approx(6.0)


def test_tpf_preview_rejects_all_nan_image(client, monkeypatch):
    class FakeFlux:
        value = np.full((2, 2, 2), np.nan, dtype=float)

    class FakeTime:
        value = np.asarray([1.0, 2.0], dtype=float)

    fake_tpf = types.SimpleNamespace(flux=FakeFlux(), time=FakeTime())
    monkeypatch.setitem(sys.modules, "lightkurve", types.SimpleNamespace(read=lambda path: fake_tpf))
    monkeypatch.setattr("orbitlab.api.main.resolve_tpf_path", lambda product_uri: product_uri)

    response = client.get("/api/v1/tpf-preview?product_uri=mast:nan")

    assert response.status_code == 422
    assert "no finite flux pixels" in response.json()["detail"]


def test_tpf_preview_wraps_unexpected_errors(client, monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "lightkurve",
        types.SimpleNamespace(read=lambda path: (_ for _ in ()).throw(ValueError("bad fits"))),
    )
    monkeypatch.setattr("orbitlab.api.main.resolve_tpf_path", lambda product_uri: product_uri)

    response = client.get("/api/v1/tpf-preview?product_uri=mast:bad")

    assert response.status_code == 500
    assert "bad fits" in response.json()["detail"]


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


def test_model_status_reports_ready_services(client, monkeypatch):
    class ReadyService:
        def validate_artifact(self):
            return types.SimpleNamespace(status="ready", source="test", version="v1", checksum="abc")

    monkeypatch.setattr("orbitlab.api.main.NigrahaService", lambda: ReadyService())
    monkeypatch.setattr("orbitlab.api.main.KeplerAstroNetService", lambda: ReadyService())
    monkeypatch.setattr("orbitlab.api.main.ExoMACService", lambda: ReadyService())
    monkeypatch.setattr("orbitlab.api.main.artifact_status", lambda model_id: {"status": "registered"})

    response = client.get("/api/v1/models")

    assert response.status_code == 200
    payload = response.json()
    assert payload["nigraha_tess"]["status"] == "ready"
    assert payload["kepler_astronet"]["source"] == "test"
    assert payload["k2_exomac_kkt"]["checksum"] == "abc"


def test_model_status_reports_unavailable_service_failures(client, monkeypatch):
    from orbitlab.exceptions import ModelArtifactError

    class MissingService:
        def validate_artifact(self):
            raise ModelArtifactError("missing model")

    monkeypatch.setattr("orbitlab.api.main.NigrahaService", lambda: MissingService())
    monkeypatch.setattr("orbitlab.api.main.KeplerAstroNetService", lambda: MissingService())
    monkeypatch.setattr("orbitlab.api.main.ExoMACService", lambda: MissingService())
    monkeypatch.setattr(
        "orbitlab.api.main.artifact_status", lambda model_id: {"status": "registered", "model_id": model_id}
    )

    response = client.get("/api/v1/models")

    assert response.status_code == 200
    payload = response.json()
    assert payload["nigraha_tess"]["status"] == "unavailable"
    assert payload["kepler_astronet"]["status"] == "unavailable"
    assert payload["k2_exomac_kkt"]["status"] == "unavailable"


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


def test_bls_preview_rejects_aperture_mask_for_different_product(client):
    with SessionLocal() as db:
        mask = ApertureMaskRecord(
            id=str(uuid4()),
            target_id="TIC 123",
            product_uri="mast:other",
            mask_json=[[True]],
            reason="wrong product",
        )
        db.add(mask)
        db.commit()
        mask_id = mask.id

    response = client.post(
        "/api/v1/bls-preview",
        json={
            "product_uri": "mast:this-product",
            "mission": "TESS",
            "aperture_mask_id": mask_id,
        },
    )

    assert response.status_code == 409
    assert "different product" in response.json()["detail"]


def test_bls_preview_rejects_missing_aperture_mask(client):
    response = client.post(
        "/api/v1/bls-preview",
        json={
            "product_uri": "mast:this-product",
            "mission": "TESS",
            "aperture_mask_id": str(uuid4()),
        },
    )

    assert response.status_code == 404
    assert "aperture mask not found" in response.json()["detail"]


def test_bls_preview_uses_legacy_run_bls_fallback(client, monkeypatch):
    from orbitlab.science.bls import BlsResult, TransitCandidate

    candidate = TransitCandidate(period=2.0, epoch=0.5, duration=0.1, depth=0.001, power=10.0, signal_to_noise=20.0)
    time = np.linspace(0, 20, 200, dtype=np.float32)
    flux = (1.0 + 0.001 * np.sin(time)).astype(np.float32)

    def raise_type_error(*args, **kwargs):
        raise TypeError("old selector signature")

    def fake_run_bls(clean_time, clean_flux):
        return BlsResult(
            candidate=candidate,
            periodogram={
                "period": np.asarray([2.0], dtype=np.float32),
                "power": np.asarray([10.0], dtype=np.float32),
                "duration": np.asarray([0.1], dtype=np.float32),
            },
            search_time=np.asarray(clean_time, dtype=np.float32),
            search_flux=np.asarray(clean_flux, dtype=np.float32),
            clean_time=np.asarray(clean_time, dtype=np.float32),
            clean_flux=np.asarray(clean_flux, dtype=np.float32),
            metadata={},
        )

    monkeypatch.setattr("orbitlab.api.main.extract_light_curve_from_tpf", lambda *args, **kwargs: (time, flux, None))
    monkeypatch.setattr("orbitlab.api.main._select_primary_candidate", raise_type_error)
    monkeypatch.setattr("orbitlab.api.main.run_bls", fake_run_bls)
    monkeypatch.setattr(
        "orbitlab.api.main.find_multi_planet_candidates",
        lambda *args, initial_candidate, **kwargs: [initial_candidate],
    )

    response = client.post(
        "/api/v1/bls-preview",
        json={"product_uri": "mast:test", "mission": "TESS", "target_id": "TIC 123", "max_candidates": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["preprocessing"]["guided_known_candidates"] == 0
    assert payload["tces"][0]["period"] == pytest.approx(2.0)


def test_bls_preview_uses_saved_aperture_and_merges_guided_and_residual_candidates(client, monkeypatch):
    from orbitlab.science.bls import BlsResult, TransitCandidate

    with SessionLocal() as db:
        mask = ApertureMaskRecord(
            id=str(uuid4()),
            target_id="TIC 123",
            product_uri="mast:test",
            mask_json=[[True, False], [False, True]],
            reason="science aperture",
        )
        db.add(mask)
        db.commit()
        mask_id = mask.id

    time = np.linspace(0, 20, 200, dtype=np.float32)
    flux = (1.0 + 0.001 * np.sin(time)).astype(np.float32)
    primary = TransitCandidate(period=2.0, epoch=0.5, duration=0.1, depth=0.001, power=10.0, signal_to_noise=20.0)
    guided = TransitCandidate(period=3.0, epoch=0.4, duration=0.1, depth=0.001, power=9.0, signal_to_noise=10.0)
    residual = TransitCandidate(period=4.0, epoch=0.3, duration=0.1, depth=0.001, power=8.0, signal_to_noise=9.0)

    bls_result = BlsResult(
        candidate=primary,
        periodogram={
            "period": np.asarray([2.0], dtype=np.float32),
            "power": np.asarray([10.0], dtype=np.float32),
            "duration": np.asarray([0.1], dtype=np.float32),
        },
        search_time=time,
        search_flux=flux,
        clean_time=time,
        clean_flux=flux,
        metadata={},
    )

    seen = {}

    def fake_extract(product_uri, aperture_mask):
        seen["aperture_mask"] = aperture_mask
        return time, flux, None

    monkeypatch.setattr("orbitlab.api.main.extract_light_curve_from_tpf", fake_extract)
    monkeypatch.setattr(
        "orbitlab.api.main._select_primary_candidate",
        lambda *args, **kwargs: (primary, bls_result, [primary, guided]),
    )
    monkeypatch.setattr(
        "orbitlab.api.main.find_multi_planet_candidates",
        lambda *args, **kwargs: [primary, residual],
    )
    monkeypatch.setattr("orbitlab.api.main._candidate_duplicate", lambda candidate, existing: False)

    response = client.post(
        "/api/v1/bls-preview",
        json={
            "product_uri": "mast:test",
            "mission": "TESS",
            "target_id": "TIC 123",
            "aperture_mask_id": mask_id,
            "max_candidates": 3,
        },
    )

    assert response.status_code == 200
    assert seen["aperture_mask"] == [[True, False], [False, True]]
    periods = [candidate["period"] for candidate in response.json()["tces"]]
    assert periods == pytest.approx([2.0, 3.0, 4.0])


def test_bls_preview_stops_guided_and_residual_merges_at_requested_limit(client, monkeypatch):
    from orbitlab.science.bls import BlsResult, TransitCandidate

    time = np.linspace(0, 20, 200, dtype=np.float32)
    flux = (1.0 + 0.001 * np.sin(time)).astype(np.float32)
    primary = TransitCandidate(period=2.0, epoch=0.5, duration=0.1, depth=0.001, power=10.0, signal_to_noise=20.0)
    extra = TransitCandidate(period=3.0, epoch=0.4, duration=0.1, depth=0.001, power=9.0, signal_to_noise=10.0)
    bls_result = BlsResult(
        candidate=primary,
        periodogram={
            "period": np.asarray([2.0], dtype=np.float32),
            "power": np.asarray([10.0], dtype=np.float32),
            "duration": np.asarray([0.1], dtype=np.float32),
        },
        search_time=time,
        search_flux=flux,
        clean_time=time,
        clean_flux=flux,
        metadata={},
    )

    monkeypatch.setattr("orbitlab.api.main.extract_light_curve_from_tpf", lambda *args, **kwargs: (time, flux, None))
    monkeypatch.setattr(
        "orbitlab.api.main._select_primary_candidate",
        lambda *args, **kwargs: (primary, bls_result, [primary, extra]),
    )
    monkeypatch.setattr("orbitlab.api.main.find_multi_planet_candidates", lambda *args, **kwargs: [primary, extra])

    response = client.post(
        "/api/v1/bls-preview",
        json={"product_uri": "mast:test", "mission": "TESS", "target_id": "TIC 123", "max_candidates": 1},
    )

    assert response.status_code == 200
    assert len(response.json()["tces"]) == 1


def test_bls_preview_skips_duplicate_guided_and_residual_candidates(client, monkeypatch):
    from orbitlab.science.bls import BlsResult, TransitCandidate

    time = np.linspace(0, 20, 200, dtype=np.float32)
    flux = (1.0 + 0.001 * np.sin(time)).astype(np.float32)
    primary = TransitCandidate(period=2.0, epoch=0.5, duration=0.1, depth=0.001, power=10.0, signal_to_noise=20.0)
    duplicate = TransitCandidate(period=2.01, epoch=0.4, duration=0.1, depth=0.001, power=9.0, signal_to_noise=10.0)
    bls_result = BlsResult(
        candidate=primary,
        periodogram={
            "period": np.asarray([2.0], dtype=np.float32),
            "power": np.asarray([10.0], dtype=np.float32),
            "duration": np.asarray([0.1], dtype=np.float32),
        },
        search_time=time,
        search_flux=flux,
        clean_time=time,
        clean_flux=flux,
        metadata={},
    )

    monkeypatch.setattr("orbitlab.api.main.extract_light_curve_from_tpf", lambda *args, **kwargs: (time, flux, None))
    monkeypatch.setattr(
        "orbitlab.api.main._select_primary_candidate",
        lambda *args, **kwargs: (primary, bls_result, [primary, duplicate]),
    )
    monkeypatch.setattr("orbitlab.api.main.find_multi_planet_candidates", lambda *args, **kwargs: [primary, duplicate])
    monkeypatch.setattr("orbitlab.api.main._candidate_duplicate", lambda candidate, existing: True)

    response = client.post(
        "/api/v1/bls-preview",
        json={"product_uri": "mast:test", "mission": "TESS", "target_id": "TIC 123", "max_candidates": 3},
    )

    assert response.status_code == 200
    assert len(response.json()["tces"]) == 1


def test_bls_preview_maps_value_and_unexpected_errors(client, monkeypatch):
    monkeypatch.setattr(
        "orbitlab.api.main.extract_light_curve_from_tpf",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad aperture")),
    )
    response = client.post("/api/v1/bls-preview", json={"product_uri": "mast:test", "mission": "TESS"})
    assert response.status_code == 422

    monkeypatch.setattr(
        "orbitlab.api.main.extract_light_curve_from_tpf",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("unexpected")),
    )
    response = client.post("/api/v1/bls-preview", json={"product_uri": "mast:test", "mission": "TESS"})
    assert response.status_code == 500


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


def test_health_degraded_when_database_unavailable(client, monkeypatch):
    class BrokenEngine:
        def connect(self):
            raise RuntimeError("db unavailable")

    monkeypatch.setattr("orbitlab.api.main.engine", BrokenEngine())

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["database"] == "unavailable"
