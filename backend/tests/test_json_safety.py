import json

import numpy as np
from astropy import units as u
from astropy.utils.masked import Masked
from orbitlab.storage.json_safety import to_jsonable


def test_to_jsonable_converts_science_library_values():
    masked_quantity = Masked([1.0, 2.0, np.inf], mask=[False, True, False]) * u.day
    payload = {
        "numpy_scalar": np.float32(1.25),
        "masked_quantity": masked_quantity,
        "array": np.array([1, 2, 3], dtype=np.int64),
        "nested": {"bad": np.nan},
    }

    safe = to_jsonable(payload)

    assert safe == {
        "numpy_scalar": 1.25,
        "masked_quantity": [1.0, None, None],
        "array": [1, 2, 3],
        "nested": {"bad": None},
    }
    json.dumps(safe, allow_nan=False)
