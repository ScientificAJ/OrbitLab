from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np


def to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | bool):
        return value
    if isinstance(value, int | np.integer):
        return int(value)
    if isinstance(value, float | np.floating):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, np.ma.core.MaskedConstant):
        return None
    if hasattr(value, "value"):
        return to_jsonable(value.value)
    if isinstance(value, np.ndarray | np.ma.MaskedArray):
        return to_jsonable(np.ma.filled(value, np.nan).tolist())
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [to_jsonable(item) for item in value]
    if hasattr(value, "item"):
        try:
            return to_jsonable(value.item())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "tolist"):
        try:
            return to_jsonable(value.tolist())
        except (TypeError, ValueError):
            pass
    return str(value)
