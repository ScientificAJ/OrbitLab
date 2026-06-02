import numpy as np
import pytest
from orbitlab.exceptions import RealDataRequiredError
from orbitlab.science.data_quality import apply_manual_jitter_mask, clean_light_curve


def test_clean_light_curve_filters_quality_and_normalizes():
    time = np.arange(10, dtype=np.float32)
    flux = np.array([9.0, 10.0, 11.0, np.nan, 10.5, 9.8, 10.1, 10.2, 10.3, 10.4], dtype=np.float32)
    quality = np.array([0, 0, 0, 0, 1, 0, 0, 0, 0, 0])

    clean_time, clean_flux = clean_light_curve(time, flux, quality)

    assert clean_time.tolist() == [0, 1, 2, 5, 6, 7, 8, 9]
    assert np.isclose(np.nanmedian(clean_flux), 1.0)
    assert clean_flux.dtype == np.float32


def test_clean_light_curve_rejects_constant_arrays():
    time = np.arange(10, dtype=np.float32)
    flux = np.ones(10, dtype=np.float32)

    with pytest.raises(RealDataRequiredError):
        clean_light_curve(time, flux)


def test_manual_jitter_mask_requires_audit_reason():
    time = np.arange(8, dtype=np.float32)
    flux = np.linspace(0.9, 1.1, 8, dtype=np.float32)
    mask = np.array([False, True, False, False, False, False, False, False])

    kept_time, kept_flux, audit = apply_manual_jitter_mask(time, flux, mask, reason="reaction wheel event")

    assert kept_time.size == 7
    assert kept_flux.size == 7
    assert audit["masked_cadences"] == 1
    assert audit["reason"] == "reaction wheel event"
