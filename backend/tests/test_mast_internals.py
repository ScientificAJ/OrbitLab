from __future__ import annotations

import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from orbitlab.science.mast import (
    ProductSummary,
    _download_mast_product,
    _mask_from_tpf,
    _resolve_existing_cache_path,
    _resolve_path_within_directory,
    _tpf_pixel_scale_arcsec,
    extract_light_curve_bundle_from_tpf,
    list_tpf_products,
    resolve_target_alias,
    resolve_tpf_path,
    row_value,
    search_targets,
)


# ---------------------------------------------------------------------------
# resolve_target_alias
# ---------------------------------------------------------------------------
def test_resolve_target_alias_normalizes_trappist_variants():
    assert resolve_target_alias("trappist") == "TRAPPIST-1"
    assert resolve_target_alias("TRAPPIST-1") == "TRAPPIST-1"
    assert resolve_target_alias("Trappist  1") == "TRAPPIST-1"
    assert resolve_target_alias("trappist1") == "TRAPPIST-1"


def test_resolve_target_alias_returns_none_for_unknown():
    assert resolve_target_alias("TIC 307210830") is None
    assert resolve_target_alias("Kepler-10") is None
    assert resolve_target_alias("") is None


# ---------------------------------------------------------------------------
# row_value
# ---------------------------------------------------------------------------
def test_row_value_reads_colnames_attribute():
    row = MagicMock()
    row.colnames = ["ID", "ra"]
    row.__getitem__ = lambda self, k: {"ID": "123456", "ra": 12.5}[k]
    assert row_value(row, "ID") == "123456"
    assert row_value(row, "ra") == 12.5


def test_row_value_returns_default_for_missing_key():
    # Use a real dict-like object that raises KeyError for missing keys
    class StrictRow:
        colnames = ["ID"]
        data = {"ID": "42"}

        def __getitem__(self, key):
            return self.data[key]

    assert row_value(StrictRow(), "missing_key", default="fallback") == "fallback"


def test_row_value_falls_back_for_no_colnames():
    row = {"ID": "42"}
    assert row_value(row, "ID") == "42"


# ---------------------------------------------------------------------------
# _resolve_path_within_directory — path traversal guard
# ---------------------------------------------------------------------------
def test_resolve_path_within_directory_allows_nested_path():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        nested = root / "subdir" / "file.fits"
        nested.parent.mkdir()
        nested.touch()
        result = _resolve_path_within_directory(nested, root)
        assert result == nested.resolve()


def test_resolve_path_within_directory_blocks_traversal():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "cache"
        root.mkdir()
        evil = Path(tmp) / "evil.fits"
        evil.touch()
        with pytest.raises(PermissionError, match="TPF path must be inside"):
            _resolve_path_within_directory(evil, root)


# ---------------------------------------------------------------------------
# _resolve_existing_cache_path
# ---------------------------------------------------------------------------
def test_resolve_existing_cache_path_accepts_valid_fits():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fits_file = root / "product.fits"
        fits_file.touch()
        result = _resolve_existing_cache_path(str(fits_file), root)
        assert result == fits_file.resolve()


def test_resolve_existing_cache_path_raises_for_missing_file():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with pytest.raises(FileNotFoundError):
            _resolve_existing_cache_path(str(root / "nonexistent.fits"), root)


def test_resolve_existing_cache_path_blocks_path_traversal():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "cache"
        root.mkdir()
        outside = Path(tmp) / "outside.fits"
        outside.touch()
        with pytest.raises(PermissionError, match="TPF path must be inside"):
            _resolve_existing_cache_path(str(outside), root)


# ---------------------------------------------------------------------------
# _tpf_pixel_scale_arcsec — mission fallbacks
# ---------------------------------------------------------------------------
def test_tpf_pixel_scale_arcsec_tess_fallback():
    tpf = MagicMock()
    tpf.wcs = None
    tpf.mission = "TESS"
    result = _tpf_pixel_scale_arcsec(tpf)
    assert result == pytest.approx(21.0)


def test_tpf_pixel_scale_arcsec_kepler_fallback():
    tpf = MagicMock()
    tpf.wcs = None
    tpf.mission = "Kepler"
    result = _tpf_pixel_scale_arcsec(tpf)
    assert result == pytest.approx(3.98)


def test_tpf_pixel_scale_arcsec_k2_fallback():
    tpf = MagicMock()
    tpf.wcs = None
    tpf.mission = "K2"
    result = _tpf_pixel_scale_arcsec(tpf)
    assert result == pytest.approx(3.98)


def test_tpf_pixel_scale_arcsec_unknown_returns_none():
    tpf = MagicMock()
    tpf.wcs = None
    tpf.mission = "Unknown"
    result = _tpf_pixel_scale_arcsec(tpf)
    assert result is None


def test_tpf_pixel_scale_arcsec_uses_wcs_scales_and_survives_wcs_errors():
    class _Wcs:
        def proj_plane_pixel_scales(self):
            return np.array([0.002, -0.004])

    tpf = MagicMock()
    tpf.wcs = _Wcs()
    tpf.mission = "Unknown"
    assert _tpf_pixel_scale_arcsec(tpf) == pytest.approx(10.8)

    class _BadWcs:
        def proj_plane_pixel_scales(self):
            raise RuntimeError("bad wcs")

    tpf.wcs = _BadWcs()
    assert _tpf_pixel_scale_arcsec(tpf) is None

    class _EmptyWcs:
        def proj_plane_pixel_scales(self):
            return np.array([])

    tpf.wcs = _EmptyWcs()
    tpf.mission = "TESS"
    assert _tpf_pixel_scale_arcsec(tpf) == pytest.approx(21.0)


# ---------------------------------------------------------------------------
# _mask_from_tpf
# ---------------------------------------------------------------------------
def _fake_tpf(flux_shape=(100, 5, 5), pipeline_mask=None):
    tpf = MagicMock()
    tpf.flux = MagicMock()
    tpf.flux.shape = flux_shape
    if pipeline_mask is not None:
        tpf.pipeline_mask = pipeline_mask
    else:
        mask = np.zeros((flux_shape[1], flux_shape[2]), dtype=bool)
        mask[1:4, 1:4] = True
        tpf.pipeline_mask = mask
    return tpf


def test_mask_from_tpf_list_aperture_is_accepted():
    tpf = _fake_tpf()
    mask_list = [[True, False, False, False, False]] * 5
    mask, pipeline, threshold = _mask_from_tpf(tpf, mask_list)
    assert isinstance(mask, np.ndarray)
    assert mask.dtype == bool
    assert mask.any()


def test_mask_from_tpf_list_shape_mismatch_raises():
    tpf = _fake_tpf()
    wrong_shape = [[True, False], [False, True]]
    with pytest.raises(ValueError, match="aperture mask shape"):
        _mask_from_tpf(tpf, wrong_shape)


def test_mask_from_tpf_all_false_list_raises():
    tpf = _fake_tpf()
    all_false = [[False] * 5] * 5
    with pytest.raises(ValueError, match="aperture mask must select at least one pixel"):
        _mask_from_tpf(tpf, all_false)


def test_mask_from_tpf_pipeline_mode_uses_pipeline_mask():
    pipeline = np.zeros((5, 5), dtype=bool)
    pipeline[2, 2] = True
    tpf = _fake_tpf(pipeline_mask=pipeline)
    mask, pm, threshold = _mask_from_tpf(tpf, "pipeline")
    assert mask[2, 2]
    assert threshold is None


def test_mask_from_tpf_pipeline_mode_falls_back_to_threshold():
    empty_pipeline = np.zeros((5, 5), dtype=bool)
    tpf = _fake_tpf(pipeline_mask=empty_pipeline)
    threshold_mask = np.zeros((5, 5), dtype=bool)
    threshold_mask[2, 2] = True
    tpf.create_threshold_mask = MagicMock(return_value=threshold_mask)
    mask, pm, threshold = _mask_from_tpf(tpf, "pipeline")
    assert mask[2, 2]
    assert threshold is not None


def test_mask_from_tpf_pipeline_no_pixels_raises():
    empty = np.zeros((5, 5), dtype=bool)
    tpf = _fake_tpf(pipeline_mask=empty)
    tpf.create_threshold_mask = MagicMock(return_value=empty)
    with pytest.raises(ValueError, match="no usable pipeline or threshold aperture pixels"):
        _mask_from_tpf(tpf, "pipeline")


def test_mask_from_tpf_passthrough_mode_returns_original_mask_and_pipeline():
    tpf = _fake_tpf()
    mask, pipeline, threshold = _mask_from_tpf(tpf, None)

    assert mask is None
    assert pipeline.shape == (5, 5)
    assert threshold is None


# ---------------------------------------------------------------------------
# search_targets — alias and name-first rows
# ---------------------------------------------------------------------------
def test_search_targets_trappist_alias_always_returned(monkeypatch):
    import astroquery.mast as mast_module

    monkeypatch.setattr(
        mast_module.Catalogs,
        "query_object",
        staticmethod(lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("MAST unreachable"))),
    )

    results = search_targets("trappist", mission="TESS")
    ids = [r["target_id"] for r in results]
    assert "TRAPPIST-1" in ids
    alias = next(r for r in results if r["target_id"] == "TRAPPIST-1")
    assert alias["match_type"] == "alias"


def test_search_targets_free_text_name_row_prepended(monkeypatch):
    class _FakeTable:
        def __getitem__(self, _):
            return self

        def __len__(self):
            return 0

        def __iter__(self):
            return iter([])

        colnames = []

    monkeypatch.setattr("astroquery.mast.Catalogs.query_object", lambda *a, **kw: _FakeTable())

    results = search_targets("TOI-700", mission="TESS")
    name_rows = [r for r in results if r["match_type"] == "catalog" and r["catalog"] == "NAME"]
    assert len(name_rows) == 1
    assert name_rows[0]["target_id"] == "TOI-700"
    assert name_rows[0]["trust_state"] == "name_unverified"


def test_search_targets_uses_kic_catalog_for_kepler(monkeypatch):
    captured = {}

    class _FakeTable:
        def __getitem__(self, _):
            return self

        def __len__(self):
            return 0

        def __iter__(self):
            return iter([])

        colnames = []

    def fake_query(query, catalog, **kwargs):
        captured["catalog"] = catalog
        return _FakeTable()

    monkeypatch.setattr("astroquery.mast.Catalogs.query_object", fake_query)

    search_targets("Kepler-10", mission="Kepler")
    assert captured.get("catalog") == "KIC"


def test_search_targets_uses_epic_catalog_for_k2(monkeypatch):
    captured = {}

    class _FakeTable:
        def __getitem__(self, _):
            return self

        def __len__(self):
            return 0

        def __iter__(self):
            return iter([])

        colnames = []

    def fake_query(query, catalog, **kwargs):
        captured["catalog"] = catalog
        return _FakeTable()

    monkeypatch.setattr("astroquery.mast.Catalogs.query_object", fake_query)

    search_targets("EPIC 201498078", mission="K2")
    assert captured.get("catalog") == "EPIC"


def test_search_targets_reraises_tess_catalog_failure_for_numeric_query(monkeypatch):
    monkeypatch.setattr(
        "astroquery.mast.Catalogs.query_object",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("TIC service down")),
    )

    with pytest.raises(RuntimeError, match="TIC service down"):
        search_targets("123456789", mission="TESS")


def test_search_targets_returns_mission_fallback_for_numeric_kepler_catalog_failure(monkeypatch):
    monkeypatch.setattr(
        "astroquery.mast.Catalogs.query_object",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("KIC service down")),
    )

    results = search_targets("11904151", mission="Kepler")

    assert results == [
        {
            "target_id": "11904151",
            "ra": None,
            "dec": None,
            "catalog": "KIC",
            "match_type": "catalog",
            "matched_query": None,
            "trust_state": "mission_fallback_unverified",
            "trust_label": "Mission fallback row; product lookup must prove this target.",
            "trust_warnings": ["catalog_query_failed"],
        }
    ]


def test_search_targets_skips_duplicate_catalog_rows(monkeypatch):
    class _Row(dict):
        colnames = ["ID", "ra", "dec"]

    class _FakeTable:
        def __getitem__(self, _):
            return self

        def __iter__(self):
            return iter(
                [
                    _Row(ID="123456789", ra=1.0, dec=2.0),
                    _Row(ID="123456789", ra=1.1, dec=2.1),
                ]
            )

    monkeypatch.setattr("astroquery.mast.Catalogs.query_object", lambda *a, **kw: _FakeTable())

    results = search_targets("123456789", mission="TESS")

    assert [item["target_id"] for item in results] == ["123456789"]


# ---------------------------------------------------------------------------
# list_tpf_products — lightkurve and astroquery fallbacks
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("mission", "raw_target", "expected_target"),
    [
        ("TESS", "123456789", "TIC 123456789"),
        ("Kepler", "11904151", "KIC 11904151"),
        ("K2", "201498078", "EPIC 201498078"),
    ],
)
def test_list_tpf_products_uses_lightkurve_results_and_numeric_mission_prefixes(
    monkeypatch, mission, raw_target, expected_target
):
    captured = {}

    class _Search:
        table = [
            {"dataURI": "", "productFilename": "skip-me.fits"},
            {
                "dataURI": "mast:TESS/product/tpf.fits",
                "productFilename": "tpf.fits",
                "description": "Target Pixel File",
                "obsID": "obs-1",
                "mission": mission,
                "size": "42",
            },
        ]

        def __len__(self):
            return len(self.table)

    def search_targetpixelfile(target_name, mission=None):
        captured["target_name"] = target_name
        captured["mission"] = mission
        return _Search()

    monkeypatch.setitem(sys.modules, "lightkurve", types.SimpleNamespace(search_targetpixelfile=search_targetpixelfile))

    products = list_tpf_products(raw_target, mission=mission)

    assert captured == {"target_name": expected_target, "mission": mission}
    assert products == [
        ProductSummary(
            product_id="obs-1",
            mission=mission,
            description="Target Pixel File",
            size=42,
            product_uri="mast:TESS/product/tpf.fits",
        )
    ]


def test_list_tpf_products_returns_empty_when_mast_observations_or_products_are_empty(monkeypatch):
    class _EmptySearch:
        table = []

        def __len__(self):
            return 0

    monkeypatch.setitem(
        sys.modules,
        "lightkurve",
        types.SimpleNamespace(search_targetpixelfile=lambda *a, **kw: _EmptySearch()),
    )

    class _EmptyObservations:
        @staticmethod
        def query_criteria(**criteria):
            return []

        @staticmethod
        def get_product_list(obs):
            raise AssertionError("empty observations should return before product lookup")

    monkeypatch.setattr("astroquery.mast.Observations", _EmptyObservations)
    assert list_tpf_products("TOI-700", mission="TESS") == []

    class _NoProductsObservations:
        @staticmethod
        def query_criteria(**criteria):
            assert criteria["obs_collection"] == "Kepler"
            return [object()]

        @staticmethod
        def get_product_list(obs):
            return []

    monkeypatch.setattr("astroquery.mast.Observations", _NoProductsObservations)
    assert list_tpf_products("EPIC 201498078", mission="K2") == []


def test_list_tpf_products_filters_mast_products_to_target_pixel_files(monkeypatch):
    class _EmptySearch:
        table = []

        def __len__(self):
            return 0

    monkeypatch.setitem(
        sys.modules,
        "lightkurve",
        types.SimpleNamespace(search_targetpixelfile=lambda *a, **kw: _EmptySearch()),
    )

    class _Observations:
        @staticmethod
        def query_criteria(**criteria):
            return [object()]

        @staticmethod
        def get_product_list(obs):
            return [
                {"dataURI": "", "description": "Target Pixel File", "productFilename": "empty.fits"},
                {
                    "dataURI": "mast:TESS/product/lightcurve.fits",
                    "description": "Light curve",
                    "productFilename": "lc.fits",
                    "productType": "SCIENCE",
                },
                {
                    "dataURI": "mast:TESS/product/tpf.fits",
                    "description": "TargetPixel data",
                    "productFilename": "target-tpf.fits",
                    "productType": "SCIENCE",
                    "obsID": "obs-2",
                    "obs_collection": "TESS",
                    "size": "99",
                },
            ]

    monkeypatch.setattr("astroquery.mast.Observations", _Observations)

    products = list_tpf_products("TOI-700", mission="TESS")

    assert products == [
        ProductSummary(
            product_id="obs-2",
            mission="TESS",
            description="TargetPixel data",
            size=99,
            product_uri="mast:TESS/product/tpf.fits",
        )
    ]


def test_list_tpf_products_allows_numeric_target_without_mission_prefix_and_no_mission_filter(monkeypatch):
    captured = {}

    class _EmptySearch:
        table = []

        def __len__(self):
            return 0

    def search_targetpixelfile(target_name, mission=None):
        captured["target_name"] = target_name
        return _EmptySearch()

    monkeypatch.setitem(sys.modules, "lightkurve", types.SimpleNamespace(search_targetpixelfile=search_targetpixelfile))

    class _EmptyObservations:
        @staticmethod
        def query_criteria(**criteria):
            captured["criteria"] = criteria
            return []

        @staticmethod
        def get_product_list(obs):
            raise AssertionError("empty observations should return first")

    monkeypatch.setattr("astroquery.mast.Observations", _EmptyObservations)

    assert list_tpf_products("123456789", mission=None) == []
    assert captured["target_name"] == "123456789"
    assert "obs_collection" not in captured["criteria"]


# ---------------------------------------------------------------------------
# MAST downloads and TPF extraction guards
# ---------------------------------------------------------------------------
def test_download_mast_product_handles_directory_destination_and_fallbacks(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    downloaded_dir = cache / "mastDownload"
    downloaded_dir.mkdir(parents=True)
    (downloaded_dir / "nested.fits").write_bytes(b"fits")

    class _DirectoryManifest:
        @staticmethod
        def download_file(product_uri, *, local_path, cache):
            return str(downloaded_dir)

    monkeypatch.setattr("astroquery.mast.Observations", _DirectoryManifest)
    assert _download_mast_product("mast:TESS/product/file.fits", cache) == downloaded_dir / "nested.fits"

    class _DestinationFallback:
        @staticmethod
        def download_file(product_uri, *, local_path, cache):
            Path(local_path).write_bytes(b"fits")
            return str(tmp_path / "missing-manifest.fits")

    monkeypatch.setattr("astroquery.mast.Observations", _DestinationFallback)
    assert _download_mast_product("https://example.test/file.fits", cache).name == "file.fits"

    fallback = cache / "zzzz-late.fits"
    fallback.write_bytes(b"fits")

    class _MastUriFallback:
        @staticmethod
        def download_file(product_uri, *, local_path, cache):
            return str(tmp_path / "still-missing.fits")

    monkeypatch.setattr("astroquery.mast.Observations", _MastUriFallback)
    assert _download_mast_product("mast:TESS/product/missing.fits", cache) == fallback

    empty_dir = cache / "empty-download"
    empty_dir.mkdir()

    class _EmptyDirectoryManifest:
        @staticmethod
        def download_file(product_uri, *, local_path, cache):
            return empty_dir

    monkeypatch.setattr("astroquery.mast.Observations", _EmptyDirectoryManifest)
    with pytest.raises(FileNotFoundError, match="no FITS files"):
        _download_mast_product("mast:TESS/product/empty.fits", cache)

    class _Missing:
        @staticmethod
        def download_file(product_uri, *, local_path, cache):
            return str(tmp_path / "uncreated.fits")

    clean_cache = tmp_path / "clean-cache"
    monkeypatch.setattr("astroquery.mast.Observations", _Missing)
    with pytest.raises(FileNotFoundError, match="did not create"):
        _download_mast_product("https://example.test/uncreated.fits", clean_cache)

    with pytest.raises(FileNotFoundError, match="did not create"):
        _download_mast_product("mast:TESS/product/uncreated.fits", tmp_path / "mast-clean-cache")


def test_resolve_tpf_path_downloads_mast_uri_and_rejects_external_manifest(tmp_path, monkeypatch):
    cache = tmp_path / "cache"

    class _CreatesDestination:
        @staticmethod
        def download_file(product_uri, *, local_path, cache):
            Path(local_path).write_bytes(b"fits")
            return local_path

    monkeypatch.setattr("astroquery.mast.Observations", _CreatesDestination)
    assert resolve_tpf_path("mast:TESS/product/file.fits", cache_dir=cache).name == "file.fits"
    assert resolve_tpf_path("file.fits", cache_dir=cache).name == "file.fits"

    outside = tmp_path / "outside.fits"
    outside.write_bytes(b"fits")

    class _ExternalManifest:
        @staticmethod
        def download_file(product_uri, *, local_path, cache):
            return str(outside)

    monkeypatch.setattr("astroquery.mast.Observations", _ExternalManifest)
    with pytest.raises(PermissionError, match="inside the configured MAST cache"):
        _download_mast_product("mast:TESS/product/outside.fits", cache)


def test_extract_light_curve_bundle_rejects_non_tpf_file(tmp_path, monkeypatch):
    product = tmp_path / "not-a-tpf.fits"
    product.write_bytes(b"fits")
    monkeypatch.setitem(sys.modules, "lightkurve", types.SimpleNamespace(read=lambda path: object()))
    monkeypatch.setattr("orbitlab.science.mast.resolve_tpf_path", lambda product_uri: product)

    with pytest.raises(TypeError, match="not a Lightkurve target pixel file"):
        extract_light_curve_bundle_from_tpf(str(product), aperture_mask="pipeline")


# ---------------------------------------------------------------------------
# ProductSummary — dataclass contract
# ---------------------------------------------------------------------------
def test_product_summary_is_immutable():
    ps = ProductSummary(
        product_id="obs-001",
        mission="TESS",
        description="Target Pixel File",
        size=1024,
        product_uri="mast:TESS/product/file.fits",
    )
    with pytest.raises((AttributeError, TypeError)):
        ps.mission = "Kepler"  # type: ignore[misc]
