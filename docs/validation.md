# Validation against FLIR Research Studio (Milestone 2) — template, no results yet

Two distinct questions, recorded separately:

* **A. Software equivalence** – does this application interpret the camera data the same way
  Research Studio does? Establishable without a blackbody.
* **B. Absolute camera calibration** – does the camera measure a traceable temperature?
  Cannot be claimed from A; requires a reference source.

## Protocol (to be executed once the probe has run)

1. Same camera, same scene, same object parameters and range in both tools; record them here.
2. Compare at ≥3 scene temperatures spanning the experimental range (room temperature, ~100 °C,
   ~180 °C): center pixel, user-selected pixel, ROI min/max/mean, full-frame min/max.
3. Report as a table: location, Research Studio value, this application's value, difference.

| Date | Range/case | Emissivity | T_refl | Location | Research Studio (°C) | FLIR Research Interface (°C) | Δ (°C) |
|---|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — | — |

Results, and any discrepancy explanation, go here. Until this table is filled, the application
is **not** validated for experimental use.
