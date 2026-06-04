from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from orbitlab.science.mast import (
    ProductSummary,
    _mask_from_tpf,
    _resolve_existing_cache_path,
    _resolve_path_within_directory,
    _tpf_pixel_scale_arcsec,
    resolve_target_alias,
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


# ---------------------------------------------------------------------------
# search_targets — alias and name-first rows
# ---------------------------------------------------------------------------
def test_search_targets_trappist_alias_always_returned(monkeypatch):
    import astroquery.mast as mast_module

    monkeypatch.setattr(mast_module.Catalogs, "query_object", staticmethod(lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("MAST unreachable"))))

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
