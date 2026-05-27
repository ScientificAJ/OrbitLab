from __future__ import annotations

import sys
import types

import numpy as np
from orbitlab.science.bls import TransitCandidate
from orbitlab.science.catalog_context import query_tic_catalog_context
from orbitlab.science.dave_vetting import run_model_shift
from orbitlab.science.detrending import detrend_with_wotan
from orbitlab.science.triceratops_fpp import parse_tess_sector, run_triceratops_fpp


class _FakeTable:
    def __init__(self, rows):
        self._rows = rows
        self.colnames = list(rows[0].keys()) if rows else []

    def __iter__(self):
        return iter(self._rows)


def test_wotan_biweight_detrending_runs_real_package():
    time = np.linspace(0, 12, 240)
    flux = 1.0 + 0.01 * np.sin(time / 3.0) - 0.001 * (np.abs((time % 2.0) - 0.1) < 0.04)

    detrended, metadata = detrend_with_wotan(time, flux, method="biweight", window_length_days=0.75)

    assert metadata["status"] == "complete"
    assert metadata["engine"] == "wotan"
    assert detrended.shape == time.shape
    assert np.isfinite(detrended).all()


def test_tic_catalog_context_flags_neighbor_that_can_mimic_depth(monkeypatch):
    from astroquery.ipac.nexsci.nasa_exoplanet_archive import NasaExoplanetArchive
    from astroquery.mast import Catalogs

    rows = _FakeTable(
        [
            {"ID": "123456789", "ra": 10.0, "dec": 20.0, "Tmag": 10.0, "GAIA": "target-gaia"},
            {"ID": "987654321", "ra": 10.001, "dec": 20.0, "Tmag": 12.0, "GAIA": "neighbor-gaia"},
        ]
    )
    monkeypatch.setattr(Catalogs, "query_object", lambda *args, **kwargs: rows)

    def fake_archive_query(*, table, **kwargs):
        if table == "toi":
            return _FakeTable([{"toi": 123.01, "tid": 123456789, "tfopwg_disp": "PC"}])
        return _FakeTable([{"pl_name": "Test b", "hostname": "TIC 123456789", "tic_id": "TIC 123456789"}])

    monkeypatch.setattr(NasaExoplanetArchive, "query_criteria", fake_archive_query)

    context = query_tic_catalog_context("TIC 123456789", observed_depth=0.01)

    assert context["status"] == "complete"
    assert context["gaia"]["target_gaia_id"] == "target-gaia"
    assert context["exofop_toi"]["match_count"] == 1
    assert context["nasa_exoplanet_archive"]["confirmed_planet_count"] == 1
    assert context["contamination"]["status"] == "warning"
    assert context["contamination"]["capable_neighbor_count"] == 1


def test_dave_model_shift_uses_official_binary_output(tmp_path):
    binary = tmp_path / "modshift"
    binary.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' 'plot 12.0 0.0 0.0 0.0 0.0 1.0 0.1 7.0 3.0 1.0 0.0 0.5 0.25 0.75 0.0 0.0'\n"
    )
    binary.chmod(0o755)
    time = np.linspace(0, 12, 300)
    flux = np.ones_like(time)
    candidate = TransitCandidate(period=2.0, epoch=0.1, duration=0.08, depth=0.002, power=8.0, signal_to_noise=9.0)

    result = run_model_shift(time, flux, candidate, modshift_binary=binary)

    assert result["status"] == "pass"
    assert result["robovet"]["disp"] == "candidate"
    assert result["modshift"]["mod_sig_pri"] == 12.0
    assert result["source"] == "Official DAVE ModShift binary with DAVE RoboVet thresholds"


def test_triceratops_wrapper_runs_installed_api_shape_with_legacy_shims(monkeypatch):
    class _FakeProbs:
        def to_dict(self, *, orient):
            assert orient == "records"
            return [{"scenario": "TP", "prob": 0.99}]

    class _FakeTarget:
        def __init__(self, *, ID, sectors):
            self.ID = ID
            self.sectors = sectors
            self.FPP = 1.0
            self.NFPP = 1.0
            self.probs = _FakeProbs()

        def calc_probs(self, **kwargs):
            assert kwargs["P_orb"] == 2.0
            assert kwargs["N"] == 1000
            self.FPP = 0.002
            self.NFPP = 0.0002

    fake_module = types.SimpleNamespace(target=_FakeTarget)
    monkeypatch.setitem(sys.modules, "triceratops", types.ModuleType("triceratops"))
    monkeypatch.setitem(sys.modules, "triceratops.triceratops", fake_module)

    time = np.linspace(0, 12, 300)
    flux = np.ones_like(time)
    candidate = TransitCandidate(period=2.0, epoch=0.1, duration=0.08, depth=0.002, power=8.0, signal_to_noise=9.0)

    result = run_triceratops_fpp(
        target_id="TIC 123456789",
        product_uri="tess2020000000000-s0007-0000000123456789-tp.fits",
        time=time,
        flux=flux + np.random.default_rng(1).normal(0, 1e-4, size=time.size),
        candidate=candidate,
        samples=1000,
    )

    assert parse_tess_sector("tess-s0123-target.fits") == 123
    assert result["status"] == "complete"
    assert result["target_id"] == 123456789
    assert result["sector"] == 7
    assert result["fpp"] == 0.002
    assert result["nfpp"] == 0.0002
