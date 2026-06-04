from __future__ import annotations

import json

import numpy as np
import pytest
from orbitlab.storage.json_safety import to_jsonable


# ---------------------------------------------------------------------------
# Basic scalar types
# ---------------------------------------------------------------------------
def test_to_jsonable_passthrough_for_primitives():
    assert to_jsonable(None) is None
    assert to_jsonable(True) is True
    assert to_jsonable(False) is False
    assert to_jsonable("hello") == "hello"


def test_to_jsonable_converts_numpy_integers():
    for dtype in (np.int8, np.int16, np.int32, np.int64, np.uint8, np.uint32):
        result = to_jsonable(dtype(42))
        assert result == 42
        assert isinstance(result, int)


def test_to_jsonable_converts_numpy_floats():
    for dtype in (np.float16, np.float32, np.float64):
        result = to_jsonable(dtype(1.5))
        assert isinstance(result, float)
        assert result == pytest.approx(1.5, rel=1e-3)


def test_to_jsonable_nan_becomes_none():
    assert to_jsonable(float("nan")) is None
    assert to_jsonable(np.float32("nan")) is None
    assert to_jsonable(np.float64("nan")) is None


def test_to_jsonable_inf_becomes_none():
    assert to_jsonable(float("inf")) is None
    assert to_jsonable(float("-inf")) is None
    assert to_jsonable(np.float64("inf")) is None


# ---------------------------------------------------------------------------
# Numpy arrays
# ---------------------------------------------------------------------------
def test_to_jsonable_plain_ndarray():
    arr = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    result = to_jsonable(arr)
    assert result == [1.0, 2.0, 3.0]


def test_to_jsonable_ndarray_with_nan_converts_to_none():
    arr = np.array([1.0, float("nan"), 3.0])
    result = to_jsonable(arr)
    assert result[0] == 1.0
    assert result[1] is None
    assert result[2] == 3.0


def test_to_jsonable_integer_ndarray():
    arr = np.array([10, 20, 30], dtype=np.int64)
    result = to_jsonable(arr)
    assert result == [10, 20, 30]
    assert all(isinstance(v, int) for v in result)


def test_to_jsonable_2d_ndarray():
    arr = np.array([[1, 2], [3, 4]], dtype=np.int32)
    result = to_jsonable(arr)
    assert result == [[1, 2], [3, 4]]


# ---------------------------------------------------------------------------
# Masked arrays
# ---------------------------------------------------------------------------
def test_to_jsonable_masked_array_replaces_masked_with_none():
    arr = np.ma.array([1.0, 2.0, 3.0], mask=[False, True, False])
    result = to_jsonable(arr)
    assert result[0] == 1.0
    assert result[1] is None
    assert result[2] == 3.0


def test_to_jsonable_fully_masked_array():
    arr = np.ma.array([1.0, 2.0], mask=[True, True])
    result = to_jsonable(arr)
    assert result == [None, None]


def test_to_jsonable_masked_array_with_nan_under_unmasked():
    arr = np.ma.array([float("nan"), 2.0], mask=[False, False])
    result = to_jsonable(arr)
    assert result[0] is None
    assert result[1] == 2.0


# ---------------------------------------------------------------------------
# np.ma.core.MaskedConstant (the singleton fill_value sentinel)
# ---------------------------------------------------------------------------
def test_to_jsonable_masked_constant_is_none():
    assert to_jsonable(np.ma.masked) is None


# ---------------------------------------------------------------------------
# Containers
# ---------------------------------------------------------------------------
def test_to_jsonable_dict_recurses():
    payload = {"a": np.float32(1.0), "b": {"c": np.int64(7)}}
    result = to_jsonable(payload)
    assert result == {"a": 1.0, "b": {"c": 7}}


def test_to_jsonable_dict_keys_become_strings():
    payload = {1: "one", 2: "two"}
    result = to_jsonable(payload)
    assert "1" in result and "2" in result


def test_to_jsonable_list_recurses():
    payload = [np.float32(1.0), np.nan, None, "ok"]
    result = to_jsonable(payload)
    assert result == [1.0, None, None, "ok"]


def test_to_jsonable_tuple_converts_to_list():
    result = to_jsonable((np.int32(1), np.float32(2.5)))
    assert result == [1, 2.5]
    assert isinstance(result, list)


def test_to_jsonable_set_converts_to_list():
    result = to_jsonable({np.int64(1), np.int64(2)})
    assert sorted(result) == [1, 2]


# ---------------------------------------------------------------------------
# Objects with .value (astropy Quantity-style)
# ---------------------------------------------------------------------------
def test_to_jsonable_object_with_value_attribute():
    class FakeQuantity:
        def __init__(self, v):
            self.value = v

    result = to_jsonable(FakeQuantity(np.float32(3.14)))
    assert result == pytest.approx(3.14, rel=1e-3)


def test_to_jsonable_nested_value_chain():
    class Outer:
        class Inner:
            value = np.float64(2.71)
        value = Inner()

    result = to_jsonable(Outer())
    assert result == pytest.approx(2.71)


# ---------------------------------------------------------------------------
# JSON round-trip safety (no NaN / Infinity / non-serialisable types)
# ---------------------------------------------------------------------------
def test_to_jsonable_output_is_always_json_serialisable():
    complex_payload = {
        "a": np.float32("nan"),
        "b": np.inf,
        "c": np.array([1, np.nan, 3]),
        "d": np.ma.array([1.0, 2.0], mask=[True, False]),
        "e": {"f": np.int64(99)},
        "g": [np.float16(0.5), None, True],
    }
    safe = to_jsonable(complex_payload)
    serialized = json.dumps(safe, allow_nan=False)
    roundtripped = json.loads(serialized)
    assert roundtripped["a"] is None
    assert roundtripped["b"] is None
    assert roundtripped["e"]["f"] == 99


def test_to_jsonable_fallback_stringifies_unknown_objects():
    class Weird:
        def __str__(self):
            return "weird_object"

    result = to_jsonable(Weird())
    assert result == "weird_object"
