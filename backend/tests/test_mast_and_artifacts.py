from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import fetch_kepler_astronet
from orbitlab.ml.artifact_registry import (
    K2_ASTRONET_MODEL_ID,
    K2_EXOMAC_MODEL_ID,
    K2_UNAVAILABLE_DETAIL,
    artifact_status,
    get_registered_artifact,
    register_artifact,
)
from orbitlab.ml.checksum import sha256_path
from orbitlab.science.mast import resolve_tpf_path


def test_resolve_tpf_path_accepts_existing_fits_file(tmp_path: Path):
    tpf = tmp_path / "real-tpf.fits"
    tpf.write_bytes(b"fits bytes")

    assert resolve_tpf_path(str(tpf)) == tpf.resolve()


def test_register_artifact_records_checksum_and_metadata(tmp_path: Path):
    artifact_path = tmp_path / "astronet.onnx"
    artifact_path.write_bytes(b"published checkpoint bytes")
    registry_path = tmp_path / "models.json"

    artifact = register_artifact(
        model_id="kepler-astronet",
        mission="Kepler",
        path=artifact_path,
        source="Google Research exoplanet-ml AstroNet",
        version="registered-test",
        registry_path=registry_path,
    )
    loaded = get_registered_artifact("kepler-astronet", registry_path=registry_path)

    assert artifact.sha256 == sha256_path(artifact_path)
    assert loaded.path == str(artifact_path.resolve())
    assert loaded.mission == "Kepler"
    assert loaded.format == "onnx"


def test_register_artifact_records_npz_format(tmp_path: Path):
    artifact_path = tmp_path / "kepler.npz"
    artifact_path.write_bytes(b"converted numpy artifact")
    registry_path = tmp_path / "models.json"

    artifact = register_artifact(
        model_id="kepler-astronet-cnn-bilstm-attention",
        mission="Kepler",
        path=artifact_path,
        source="registered Kepler NumPy artifact",
        version="npz-test",
        registry_path=registry_path,
    )

    assert artifact.format == "numpy-npz"
    assert artifact_status("kepler-astronet-cnn-bilstm-attention", registry_path)["status"] == "ready"


def test_register_artifact_records_exomac_bundle_format(tmp_path: Path):
    artifact_path = tmp_path / "k2-exomac"
    artifact_path.mkdir()
    (artifact_path / "exoplanet_best_model.joblib").write_bytes(b"joblib")
    registry_path = tmp_path / "models.json"

    artifact = register_artifact(
        model_id=K2_EXOMAC_MODEL_ID,
        mission="K2",
        path=artifact_path,
        source="ExoMAC-KKT",
        version="test",
        registry_path=registry_path,
    )

    assert artifact.format == "sklearn-joblib-bundle"
    assert artifact_status(K2_EXOMAC_MODEL_ID, registry_path)["status"] == "ready"


def test_k2_status_is_explicitly_unavailable(tmp_path: Path):
    status = artifact_status(K2_ASTRONET_MODEL_ID, tmp_path / "models.json")

    assert status["status"] == "unavailable"
    assert status["detail"] == K2_UNAVAILABLE_DETAIL


def test_kepler_fetcher_rejects_lfs_pointer():
    payload = b"version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 123\n"

    with pytest.raises(ValueError, match="Git LFS pointer"):
        fetch_kepler_astronet.reject_lfs_pointer(payload, "model.ckpt.index")


def test_kepler_fetcher_validates_downloaded_hashes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    payloads = {
        name: f"checkpoint bytes for {name}".encode("utf-8")
        for name in fetch_kepler_astronet.CHECKPOINT_FILES
    }
    monkeypatch.setattr(
        fetch_kepler_astronet,
        "CHECKPOINT_FILES",
        {name: fetch_kepler_astronet.sha256_bytes(payload) for name, payload in payloads.items()},
    )
    monkeypatch.setattr(
        fetch_kepler_astronet,
        "download_file",
        lambda url: payloads[url.rsplit("/", 1)[-1]],
    )

    written = fetch_kepler_astronet.fetch_checkpoint(tmp_path)

    assert sorted(path.name for path in written) == sorted(payloads)
