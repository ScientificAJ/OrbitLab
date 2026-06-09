import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import fetch_kepler_astronet
from orbitlab.exceptions import ModelArtifactError
from orbitlab.ml.artifact_registry import (
    K2_EXOMAC_MODEL_ID,
    artifact_status,
    get_registered_artifact,
    register_artifact,
)
from orbitlab.ml.checksum import sha256_path
from orbitlab.science.mast import (
    extract_light_curve_bundle_from_tpf,
    extract_light_curve_from_tpf,
    resolve_target_alias,
    resolve_tpf_path,
    search_targets,
)


def test_resolve_tpf_path_accepts_existing_fits_file(tmp_path: Path):
    cache_dir = tmp_path / "mast-cache"
    cache_dir.mkdir()
    tpf = cache_dir / "real-tpf.fits"
    tpf.write_bytes(b"fits bytes")

    assert resolve_tpf_path(str(tpf), cache_dir=cache_dir) == tpf.resolve()


def test_resolve_tpf_path_rejects_existing_file_outside_cache(tmp_path: Path):
    cache_dir = tmp_path / "mast-cache"
    cache_dir.mkdir()
    outside_tpf = tmp_path / "outside.fits"
    outside_tpf.write_bytes(b"fits bytes")

    with pytest.raises(PermissionError, match="configured MAST cache"):
        resolve_tpf_path(str(outside_tpf), cache_dir=cache_dir)


def test_resolve_tpf_path_rejects_cache_symlink_escape(tmp_path: Path):
    cache_dir = tmp_path / "mast-cache"
    cache_dir.mkdir()
    outside_tpf = tmp_path / "outside.fits"
    outside_tpf.write_bytes(b"fits bytes")
    symlink = cache_dir / "linked.fits"
    symlink.symlink_to(outside_tpf)

    with pytest.raises(PermissionError, match="configured MAST cache"):
        resolve_tpf_path(str(symlink), cache_dir=cache_dir)


def test_kepler_search_falls_back_when_catalog_adapter_is_missing(monkeypatch: pytest.MonkeyPatch):
    class Catalogs:
        @staticmethod
        def query_object(*args, **kwargs):
            raise RuntimeError("Unable to Locate Adaptor for service: Mast.Catalogs.KIC.Cone")

    mast = ModuleType("astroquery.mast")
    mast.Catalogs = Catalogs
    monkeypatch.setitem(sys.modules, "astroquery", ModuleType("astroquery"))
    monkeypatch.setitem(sys.modules, "astroquery.mast", mast)

    assert search_targets("Kepler-10", mission="Kepler") == [
        {
            "target_id": "Kepler-10",
            "ra": None,
            "dec": None,
            "catalog": "NAME",
            "match_type": "catalog",
            "matched_query": None,
            "trust_state": "name_unverified",
            "trust_label": "Typed name accepted before a mission catalog ID is proven.",
            "trust_warnings": ["free_text_name_not_catalog_verified"],
        }
    ]


def test_named_tess_search_includes_exact_query_before_nearby_catalog_rows(monkeypatch: pytest.MonkeyPatch):
    class FakeRow(dict):
        colnames = ["ID", "ra", "dec"]

    class Catalogs:
        @staticmethod
        def query_object(*args, **kwargs):
            return [FakeRow(ID="278892590", ra=346.6, dec=-5.04)]

    mast = ModuleType("astroquery.mast")
    mast.Catalogs = Catalogs
    monkeypatch.setitem(sys.modules, "astroquery", ModuleType("astroquery"))
    monkeypatch.setitem(sys.modules, "astroquery.mast", mast)

    results = search_targets("TRAPPIST-1", mission="TESS")

    assert results[0] == {
        "target_id": "TRAPPIST-1",
        "ra": None,
        "dec": None,
        "catalog": "ALIAS",
        "match_type": "alias",
        "matched_query": "TRAPPIST-1",
        "trust_state": "alias_unresolved",
        "trust_label": "Alias suggestion; select a catalog product before trusting science output.",
        "trust_warnings": ["alias_not_catalog_resolved"],
    }
    assert results[1]["target_id"] == "278892590"
    assert results[1]["trust_state"] == "catalog_resolved"
    assert results[1]["trust_warnings"] == []


@pytest.mark.parametrize("query", ["trappist", "trappist 1", "trappist-1", "trappist1"])
def test_target_alias_resolver_maps_common_trappist_names(query: str):
    assert resolve_target_alias(query) == "TRAPPIST-1"


def test_alias_search_returns_suggestion_before_catalog_rows(monkeypatch: pytest.MonkeyPatch):
    class FakeRow(dict):
        colnames = ["ID", "ra", "dec"]

    class Catalogs:
        @staticmethod
        def query_object(*args, **kwargs):
            return [FakeRow(ID="278892590", ra=346.6, dec=-5.04)]

    mast = ModuleType("astroquery.mast")
    mast.Catalogs = Catalogs
    monkeypatch.setitem(sys.modules, "astroquery", ModuleType("astroquery"))
    monkeypatch.setitem(sys.modules, "astroquery.mast", mast)

    results = search_targets("trappist", mission="TESS")

    assert results[0]["target_id"] == "TRAPPIST-1"
    assert results[0]["match_type"] == "alias"
    assert results[0]["matched_query"] == "trappist"
    assert results[0]["trust_state"] == "alias_unresolved"
    assert results[1]["target_id"] == "278892590"
    assert results[1]["match_type"] == "catalog"
    assert results[1]["trust_state"] == "catalog_resolved"


def test_alias_search_survives_tess_catalog_resolution_failure(monkeypatch: pytest.MonkeyPatch):
    class Catalogs:
        @staticmethod
        def query_object(*args, **kwargs):
            raise RuntimeError('Could not resolve "trappist" to a sky position.')

    mast = ModuleType("astroquery.mast")
    mast.Catalogs = Catalogs
    monkeypatch.setitem(sys.modules, "astroquery", ModuleType("astroquery"))
    monkeypatch.setitem(sys.modules, "astroquery.mast", mast)

    assert search_targets("trappist", mission="TESS") == [
        {
            "target_id": "TRAPPIST-1",
            "ra": None,
            "dec": None,
            "catalog": "ALIAS",
            "match_type": "alias",
            "matched_query": "trappist",
            "trust_state": "alias_unresolved",
            "trust_label": "Alias suggestion; select a catalog product before trusting science output.",
            "trust_warnings": ["alias_not_catalog_resolved"],
        }
    ]


def test_pipeline_extraction_uses_threshold_mask_when_pipeline_mask_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cache_dir = tmp_path / "mast-cache"
    cache_dir.mkdir()
    monkeypatch.setattr("orbitlab.science.mast.settings", SimpleNamespace(mast_cache_dir=cache_dir))
    product = cache_dir / "target.fits"
    product.write_bytes(b"fits")
    used_masks = []

    class FakeTpf:
        flux = SimpleNamespace(shape=(8, 2, 2))
        pipeline_mask = [[False, False], [False, False]]

        def create_threshold_mask(self, threshold=3):
            return [[True, False], [False, False]]

        def to_lightcurve(self, aperture_mask):
            used_masks.append(aperture_mask)
            return SimpleNamespace(
                time=SimpleNamespace(value=[1, 2, 3, 4, 5, 6, 7, 8]),
                flux=SimpleNamespace(value=[1.0, 1.01, 0.99, 1.02, 0.98, 1.03, 0.97, 1.04]),
                quality=[0, 0, 0, 0, 0, 0, 0, 0],
            )

    lightkurve = ModuleType("lightkurve")
    lightkurve.read = lambda path: FakeTpf()
    monkeypatch.setitem(sys.modules, "lightkurve", lightkurve)

    extract_light_curve_from_tpf(str(product), aperture_mask="pipeline")

    assert used_masks
    assert used_masks[0].tolist() == [[True, False], [False, False]]


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


def test_register_artifact_rejects_missing_path(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="model artifact path does not exist"):
        register_artifact(
            model_id="missing-model",
            mission="Kepler",
            path=tmp_path / "missing.onnx",
            source="unit-test",
            version="missing",
            registry_path=tmp_path / "models.json",
        )


@pytest.mark.parametrize(
    ("name", "files", "expected_format"),
    [
        ("tf-checkpoint", ("model.ckpt-42.index", "model.ckpt-42.data-00000-of-00001"), "tensorflow-checkpoint"),
        ("keras-ensemble", ("fold-1.hdf5", "fold-2.hdf5"), "keras-hdf5-ensemble"),
    ],
)
def test_register_artifact_detects_directory_formats(
    tmp_path: Path, name: str, files: tuple[str, ...], expected_format: str
):
    artifact_path = tmp_path / name
    artifact_path.mkdir()
    for filename in files:
        (artifact_path / filename).write_bytes(f"bytes for {filename}".encode())

    artifact = register_artifact(
        model_id=f"{name}-model",
        mission="Kepler",
        path=artifact_path,
        source="unit-test",
        version="format",
        registry_path=tmp_path / f"{name}-registry.json",
    )

    assert artifact.format == expected_format


@pytest.mark.parametrize(
    ("filename", "expected_format"),
    [
        ("forest.joblib", "sklearn-joblib"),
        ("model.h5", "keras-hdf5"),
        ("model.hdf5", "keras-hdf5"),
        ("model.keras", "keras-hdf5"),
        ("saved_model_dir_without_known_markers", "savedmodel"),
    ],
)
def test_register_artifact_detects_file_and_savedmodel_formats(tmp_path: Path, filename: str, expected_format: str):
    artifact_path = tmp_path / filename
    if "." in filename:
        artifact_path.write_bytes(b"model bytes")
    else:
        artifact_path.mkdir()
        (artifact_path / "saved_model.pb").write_bytes(b"savedmodel bytes")

    artifact = register_artifact(
        model_id=f"{filename}-model",
        mission="Kepler",
        path=artifact_path,
        source="unit-test",
        version="format",
        registry_path=tmp_path / f"{filename}-registry.json",
    )

    assert artifact.format == expected_format


def test_artifact_status_reports_unregistered_and_corrupt_registry(tmp_path: Path):
    registry_path = tmp_path / "models.json"

    missing = artifact_status("not-registered", registry_path)
    assert missing["status"] == "unavailable"
    assert "not registered" in missing["detail"]

    registry_path.write_text("{not-json", encoding="utf-8")
    corrupt = artifact_status("not-registered", registry_path)
    assert corrupt["status"] == "unavailable"


def test_get_registered_artifact_skips_non_matching_registry_entries(tmp_path: Path):
    artifact_path = tmp_path / "target.onnx"
    artifact_path.write_bytes(b"target bytes")
    registry_path = tmp_path / "models.json"
    registry_path.write_text(
        json.dumps(
            {
                "artifacts": [
                    {
                        "model_id": "other-model",
                        "mission": "Kepler",
                        "path": str(tmp_path / "other.onnx"),
                        "sha256": "0" * 64,
                        "source": "unit-test",
                        "version": "other",
                        "format": "onnx",
                    },
                    {
                        "model_id": "target-model",
                        "mission": "Kepler",
                        "path": str(artifact_path),
                        "sha256": sha256_path(artifact_path),
                        "source": "unit-test",
                        "version": "target",
                        "format": "onnx",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    artifact = get_registered_artifact("target-model", registry_path)

    assert artifact.path == str(artifact_path)
    assert artifact.version == "target"


def test_artifact_status_reports_deleted_checksum_failure_and_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    artifact_path = tmp_path / "model.onnx"
    artifact_path.write_bytes(b"original bytes")
    registry_path = tmp_path / "models.json"
    artifact = register_artifact(
        model_id="kepler-status-test",
        mission="Kepler",
        path=artifact_path,
        source="unit-test",
        version="status",
        registry_path=registry_path,
    )

    artifact_path.unlink()
    deleted = artifact_status(artifact.model_id, registry_path)
    assert deleted["status"] == "unavailable"
    assert "does not exist" in deleted["detail"]

    artifact_path.write_bytes(b"original bytes")

    def fail_checksum(path: Path) -> str:
        raise OSError(f"cannot hash {path.name}")

    monkeypatch.setattr("orbitlab.ml.artifact_registry.sha256_path", fail_checksum)
    failed = artifact_status(artifact.model_id, registry_path)
    assert failed["status"] == "unavailable"
    assert "cannot hash" in failed["detail"]

    monkeypatch.setattr("orbitlab.ml.artifact_registry.sha256_path", lambda path: "0" * 64)
    mismatch = artifact_status(artifact.model_id, registry_path)
    assert mismatch == {
        "model_id": artifact.model_id,
        "status": "unavailable",
        "detail": "artifact checksum mismatch",
    }


def test_sha256_path_rejects_empty_model_directory(tmp_path: Path):
    (tmp_path / "empty-model").mkdir()
    with pytest.raises(ModelArtifactError, match="model directory is empty"):
        sha256_path(tmp_path / "empty-model")


def test_kepler_fetcher_rejects_lfs_pointer():
    payload = b"version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 123\n"

    with pytest.raises(ValueError, match="Git LFS pointer"):
        fetch_kepler_astronet.reject_lfs_pointer(payload, "model.ckpt.index")


def test_kepler_fetcher_validates_downloaded_hashes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    payloads = {
        name: f"checkpoint bytes for {name}".encode()
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


def test_tpf_bundle_preserves_pixel_diagnostics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cache_dir = tmp_path / "mast-cache"
    cache_dir.mkdir()
    monkeypatch.setattr("orbitlab.science.mast.settings", SimpleNamespace(mast_cache_dir=cache_dir))
    product = cache_dir / "target-bundle.fits"
    product.write_bytes(b"fits")

    class FakeTpf:
        mission = "TESS"
        row = 12
        column = 34
        flux = SimpleNamespace(
            shape=(8, 2, 2),
            value=np.arange(32, dtype=np.float32).reshape(8, 2, 2) + 100.0,
        )
        pipeline_mask = [[False, False], [False, False]]

        def create_threshold_mask(self, threshold=3):
            return [[True, False], [False, True]]

        def to_lightcurve(self, aperture_mask):
            return SimpleNamespace(
                time=SimpleNamespace(value=[1, 2, 3, 4, 5, 6, 7, 8]),
                flux=SimpleNamespace(value=[1.0, 1.01, 0.99, 1.02, 0.98, 1.03, 0.97, 1.04]),
                quality=[0, 0, 0, 0, 0, 0, 0, 0],
            )

    lightkurve = ModuleType("lightkurve")
    lightkurve.read = lambda path: FakeTpf()
    monkeypatch.setitem(sys.modules, "lightkurve", lightkurve)

    bundle = extract_light_curve_bundle_from_tpf(str(product), aperture_mask="pipeline")

    assert bundle.pixel_flux.shape == (8, 2, 2)
    assert bundle.selected_mask.tolist() == [[True, False], [False, True]]
    assert bundle.pixel_scale_arcsec == 21.0
    assert bundle.reference_row == 12.0
    assert bundle.reference_column == 34.0
