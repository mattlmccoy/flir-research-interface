"""Over-range (saturated / 16-bit-wrapped) pixel detection for TemperatureLinear counts.

When a scene exceeds the camera's range the hottest counts saturate at the 16-bit ceiling or wrap
around and read as extreme cold. Such pixels carry no valid temperature; excluding them keeps
whole-frame and ROI statistics (and the auto color range) from being poisoned by false values.
Mirrors ``frontend/src/lib/overrange.ts``.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

SAT_HI = 65000  # near uint16 max: saturated
_FLOOR = 26000  # ~ -13 C in 10 mK counts: implausibly cold in a hot scene -> wrapped
_HOT_MAX = 45000  # ~ 177 C: the frame is hot enough for over-range to be plausible


def over_range_mask(counts: npt.NDArray[np.uint16]) -> npt.NDArray[np.bool_] | None:
    """Boolean mask of over-range pixels, or ``None`` when the frame has none."""
    mask = counts >= SAT_HI
    if int(counts.max(initial=0)) >= _HOT_MAX:
        mask = mask | (counts <= _FLOOR)
    return mask if bool(mask.any()) else None
