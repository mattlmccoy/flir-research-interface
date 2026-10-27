"""Over-range (saturated / 16-bit-wrapped) pixel detection for TemperatureLinear counts.

When a scene exceeds the camera's range the hottest counts saturate at the 16-bit ceiling or wrap
around and read as extreme cold (the A70 wraps to ~-80 C). Such pixels carry no valid
temperature; excluding them keeps
whole-frame and ROI statistics (and the auto color range) from being poisoned by false values.
Mirrors ``frontend/src/lib/overrange.ts``.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

SAT_HI = 65000  # near uint16 max: saturated
FLOOR_C = -13.0  # implausibly cold in this lab -> a wrapped reading (26000 counts at 10 mK)


def over_range_mask(
    counts: npt.NDArray[np.uint16], *, kelvin_per_count: float
) -> npt.NDArray[np.bool_] | None:
    """Boolean mask of over-range pixels, or ``None`` when the frame has none.

    ``kelvin_per_count`` is the frame's TemperatureLinear scale (0.01 or 0.1): the floor is a
    temperature, so it is judged in the frame's own counts (40 C is ~3131 counts at 100 mK).

    Wrapped pixels are flagged whatever the rest of the frame reads: a small hot spot (an arc)
    can wrap while nothing around it is hot, and an unflagged wrap reads ~-80 C to the
    over-temperature guard. Erring this way only ever marks a reading invalid, never healthy."""
    floor = int((FLOOR_C + 273.15) / kelvin_per_count)
    mask = (counts >= SAT_HI) | (counts <= floor)
    return mask if bool(mask.any()) else None
