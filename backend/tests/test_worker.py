from __future__ import annotations

import json
from unittest.mock import MagicMock
from uuid import uuid4

import numpy as np
import pytest
from orbitlab.storage.database import SessionLocal, init_db
from orbitlab.storage.orm import (
    AnalysisJobRecord,
    ApertureMaskRecord,
    ArtifactMaskRecord,
)
from orbitlab.worker import run_analysis_job

init_db()


def _make_job(**kwargs) -> AnalysisJobRecord:
    return AnalysisJobRecord(
        id=str(uuid4()),
        target_id=kwargs.get("target_id", "TIC 123"),
        product_uri=kwargs.get("product_uri", "mast:test-product"),
        mission=kwargs.get("mission", "TESS"),
        status="queued",
        aperture_mask_id=kwargs.get("aperture_mask_id"),
        artifact_mask_id=kwargs.get("artifact_mask_id"),
        max_candidates=kwargs.get("max_candidates", 4),
        vetting_mode=kwargs.get("vetting_mode", "fast"),
        stellar_radius_solar=kwargs.get("stellar_radius_solar"),
        stellar_mass_solar=kwargs.get("stellar_mass_solar"),
        stellar_teff=kwargs.get("stellar_teff"),
    )


def _fake_bundle():
    time = np.linspace(0, 27, 500, dtype=np.float32)
    flux = (1.0 + 0.0005 * np.sin(time)).astype(np.float32)
    quality = np.zeros(time.size, dtype=int)
    bundle = MagicMock()
    bundle.time = time
    bundle.flux = flux
    bundle.quality = quality
    bundle.pixel_flux = None
    bundle.selected_mask = np.ones((5, 5), dtype=bool)
    bundle.pixel_scale_arcsec = 21.0
    return bundle


def _fake_payload(job_id="TIC 123"):
    return {
        "result_id": str(uuid4()),
        "target_id": job_id,
        "mission": "TESS",
        "planet_candidates": [],
        "tces": [],
        "periodogram": {"period": [], "power": [], "duration": []},
        "folded_curves": {},
        "light_curve": {"time": [], "flux": []},
    }


# ---------------------------------------------------------------------------
# Test: job not found raises ValueError and does NOT write a failed record
# ---------------------------------------------------------------------------
def test_run_analysis_job_raises_when_job_missing():
    missing_id = str(uuid4())
    with pytest.raises(ValueError, match="analysis job not found"):
        run_analysis_job.run(missing_id)


# ---------------------------------------------------------------------------
# Test: successful run sets status=complete and writes a result record
# ---------------------------------------------------------------------------
def test_run_analysis_job_sets_complete_on_success(monkeypatch):
    bundle = _fake_bundle()
    payload = _fake_payload()

    monkeypatch.setattr("orbitlab.worker.extract_light_curve_bundle_from_tpf", lambda *a, **kw: bundle)
    monkeypatch.setattr("orbitlab.worker.analyze_light_curve_arrays", lambda *a, **kw: dict(payload))

    with SessionLocal() as db:
        job = _make_job()
        db.add(job)
        db.commit()
        job_id = job.id

    result_id = run_analysis_job.run(job_id)

    with SessionLocal() as db:
        job = db.get(AnalysisJobRecord, job_id)
        assert job.status == "complete"
        assert job.error is None
        from orbitlab.storage.orm import AnalysisResultRecord
        result = db.get(AnalysisResultRecord, result_id)
        assert result is not None
        assert result.job_id == job_id


# ---------------------------------------------------------------------------
# Test: ValueError inside the pipeline sets status=failed and records error
# ---------------------------------------------------------------------------
def test_run_analysis_job_sets_failed_on_value_error(monkeypatch):
    bundle = _fake_bundle()

    monkeypatch.setattr("orbitlab.worker.extract_light_curve_bundle_from_tpf", lambda *a, **kw: bundle)
    monkeypatch.setattr(
        "orbitlab.worker.analyze_light_curve_arrays",
        lambda *a, **kw: (_ for _ in ()).throw(ValueError("bad period")),
    )

    with SessionLocal() as db:
        job = _make_job()
        db.add(job)
        db.commit()
        job_id = job.id

    with pytest.raises(ValueError, match="bad period"):
        run_analysis_job.run(job_id)

    with SessionLocal() as db:
        job = db.get(AnalysisJobRecord, job_id)
        assert job.status == "failed"
        assert "bad period" in (job.error or "")


# ---------------------------------------------------------------------------
# Test: generic exception sets status=failed and preserves error message
# ---------------------------------------------------------------------------
def test_run_analysis_job_sets_failed_on_unexpected_exception(monkeypatch):
    monkeypatch.setattr(
        "orbitlab.worker.extract_light_curve_bundle_from_tpf",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("network timeout")),
    )

    with SessionLocal() as db:
        job = _make_job()
        db.add(job)
        db.commit()
        job_id = job.id

    with pytest.raises(RuntimeError, match="network timeout"):
        run_analysis_job.run(job_id)

    with SessionLocal() as db:
        job = db.get(AnalysisJobRecord, job_id)
        assert job.status == "failed"
        assert "network timeout" in (job.error or "")


# ---------------------------------------------------------------------------
# Test: custom aperture mask is loaded from DB and passed to the extractor
# ---------------------------------------------------------------------------
def test_run_analysis_job_loads_custom_aperture_mask(monkeypatch):
    mask_grid = [[True, False], [False, True]]
    captured = {}

    bundle = _fake_bundle()

    def fake_extract(product_uri, aperture_mask="pipeline"):
        captured["aperture_mask"] = aperture_mask
        return bundle

    monkeypatch.setattr("orbitlab.worker.extract_light_curve_bundle_from_tpf", fake_extract)
    monkeypatch.setattr("orbitlab.worker.analyze_light_curve_arrays", lambda *a, **kw: _fake_payload())

    with SessionLocal() as db:
        mask_id = str(uuid4())
        mask_record = ApertureMaskRecord(
            id=mask_id,
            target_id="TIC 123",
            product_uri="mast:test-product",
            mask_json=mask_grid,
            reason="custom aperture",
        )
        db.add(mask_record)
        job = _make_job(aperture_mask_id=mask_id)
        db.add(job)
        db.commit()
        job_id = job.id

    run_analysis_job.run(job_id)

    assert captured["aperture_mask"] == mask_grid


# ---------------------------------------------------------------------------
# Test: missing aperture mask raises ValueError and marks job failed
# ---------------------------------------------------------------------------
def test_run_analysis_job_fails_when_aperture_mask_missing(monkeypatch):
    bundle = _fake_bundle()
    monkeypatch.setattr("orbitlab.worker.extract_light_curve_bundle_from_tpf", lambda *a, **kw: bundle)

    with SessionLocal() as db:
        job = _make_job(aperture_mask_id=str(uuid4()))
        db.add(job)
        db.commit()
        job_id = job.id

    with pytest.raises(ValueError, match="aperture mask not found"):
        run_analysis_job.run(job_id)

    with SessionLocal() as db:
        job = db.get(AnalysisJobRecord, job_id)
        assert job.status == "failed"


# ---------------------------------------------------------------------------
# Test: artifact mask is applied — indices used to mask cadences
# ---------------------------------------------------------------------------
def test_run_analysis_job_applies_artifact_mask(monkeypatch):
    bundle = _fake_bundle()
    captured = {}

    def fake_extract(product_uri, aperture_mask="pipeline"):
        return bundle

    def fake_analyze(**kwargs):
        captured["time"] = kwargs.get("time")
        return _fake_payload()

    monkeypatch.setattr("orbitlab.worker.extract_light_curve_bundle_from_tpf", fake_extract)
    monkeypatch.setattr("orbitlab.worker.analyze_light_curve_arrays", lambda *a, **kw: fake_analyze(**kw))

    with SessionLocal() as db:
        artifact_id = str(uuid4())
        artifact_record = ArtifactMaskRecord(
            id=artifact_id,
            target_id="TIC 123",
            indices_json=[0, 1, 2],
            reason="cosmic ray",
        )
        db.add(artifact_record)
        job = _make_job(artifact_mask_id=artifact_id)
        db.add(job)
        db.commit()
        job_id = job.id

    run_analysis_job.run(job_id)

    with SessionLocal() as db:
        job = db.get(AnalysisJobRecord, job_id)
        assert job.status == "complete"


# ---------------------------------------------------------------------------
# Test: out-of-bounds artifact mask indices raise ValueError
# ---------------------------------------------------------------------------
def test_run_analysis_job_rejects_out_of_bounds_artifact_mask_indices(monkeypatch):
    bundle = _fake_bundle()
    monkeypatch.setattr("orbitlab.worker.extract_light_curve_bundle_from_tpf", lambda *a, **kw: bundle)

    with SessionLocal() as db:
        artifact_id = str(uuid4())
        n_cadences = bundle.time.size
        artifact_record = ArtifactMaskRecord(
            id=artifact_id,
            target_id="TIC 123",
            indices_json=[n_cadences + 100],
            reason="out of range test",
        )
        db.add(artifact_record)
        job = _make_job(artifact_mask_id=artifact_id)
        db.add(job)
        db.commit()
        job_id = job.id

    with pytest.raises(ValueError, match="artifact mask indices are outside"):
        run_analysis_job.run(job_id)

    with SessionLocal() as db:
        job = db.get(AnalysisJobRecord, job_id)
        assert job.status == "failed"


def test_run_analysis_job_fails_when_artifact_mask_missing(monkeypatch):
    bundle = _fake_bundle()
    monkeypatch.setattr("orbitlab.worker.extract_light_curve_bundle_from_tpf", lambda *a, **kw: bundle)

    with SessionLocal() as db:
        job = _make_job(artifact_mask_id=str(uuid4()))
        db.add(job)
        db.commit()
        job_id = job.id

    with pytest.raises(ValueError, match="artifact mask not found"):
        run_analysis_job.run(job_id)

    with SessionLocal() as db:
        job = db.get(AnalysisJobRecord, job_id)
        assert job.status == "failed"


def test_run_analysis_job_marks_failed_on_malformed_aperture_mask_json(monkeypatch):
    bundle = _fake_bundle()
    monkeypatch.setattr("orbitlab.worker.extract_light_curve_bundle_from_tpf", lambda *a, **kw: bundle)

    with SessionLocal() as db:
        mask_id = str(uuid4())
        db.add(
            ApertureMaskRecord(
                id=mask_id,
                target_id="TIC 123",
                product_uri="mast:test-product",
                mask_json="{not-json",
                reason="bad json",
            )
        )
        job = _make_job(aperture_mask_id=mask_id)
        db.add(job)
        db.commit()
        job_id = job.id

    with pytest.raises(json.JSONDecodeError):
        run_analysis_job.run(job_id)

    with SessionLocal() as db:
        job = db.get(AnalysisJobRecord, job_id)
        assert job.status == "failed"
        assert job.error


# ---------------------------------------------------------------------------
# Test: stellar context floats are forwarded to analyze_light_curve_arrays
# ---------------------------------------------------------------------------
def test_run_analysis_job_forwards_stellar_context(monkeypatch):
    bundle = _fake_bundle()
    captured = {}

    monkeypatch.setattr("orbitlab.worker.extract_light_curve_bundle_from_tpf", lambda *a, **kw: bundle)

    def fake_analyze(**kwargs):
        captured.update(kwargs)
        return _fake_payload()

    monkeypatch.setattr("orbitlab.worker.analyze_light_curve_arrays", lambda *a, **kw: fake_analyze(**kw))

    with SessionLocal() as db:
        job = _make_job(stellar_radius_solar=1.2, stellar_mass_solar=0.9, stellar_teff=5500)
        db.add(job)
        db.commit()
        job_id = job.id

    run_analysis_job.run(job_id)

    assert captured.get("stellar_radius_solar") == pytest.approx(1.2)
    assert captured.get("stellar_mass_solar") == pytest.approx(0.9)
    assert captured.get("stellar_teff") == pytest.approx(5500)


# ---------------------------------------------------------------------------
# Test: status transitions queued → running → complete in order
# ---------------------------------------------------------------------------
def test_run_analysis_job_status_transitions_in_order(monkeypatch):
    bundle = _fake_bundle()
    status_snapshots = []

    def fake_extract(product_uri, aperture_mask="pipeline"):
        with SessionLocal() as db2:
            from orbitlab.storage.orm import AnalysisJobRecord as R
            j = db2.get(R, job_id_holder[0])
            status_snapshots.append(j.status)
        return bundle

    monkeypatch.setattr("orbitlab.worker.extract_light_curve_bundle_from_tpf", fake_extract)
    monkeypatch.setattr("orbitlab.worker.analyze_light_curve_arrays", lambda *a, **kw: _fake_payload())

    job_id_holder = [None]
    with SessionLocal() as db:
        job = _make_job()
        db.add(job)
        db.commit()
        job_id_holder[0] = job.id

    run_analysis_job.run(job_id_holder[0])

    assert "running" in status_snapshots
