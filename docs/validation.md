# Validation against FLIR Research Studio (Milestone 2)

Two distinct questions, recorded separately:

* **A. Software equivalence** – does this application interpret the camera data the same way
  Research Studio does? Establishable without a blackbody.
* **B. Absolute camera calibration** – does the camera measure a traceable physical temperature?
  Cannot be claimed from A; requires a reference source (blackbody). Out of scope here.

## Status

| Check | Result |
|---|---|
| Temperature-linear decode rule verified on the A70 (Kelvin × 0.01) | done, 2026-09-01 (docs/radiometry.md §2) |
| Internal cross-check: FLIR signal-linear formula with camera constants vs temperature-linear output | agree within ~0.5 °C on an uncontrolled scene, two frames 2 min apart |
| Research Studio comparison (A) | **not done** |

## Tool

```bash
cd backend
uv run fri-live --seconds 10 --spot 320,240 --spot 100,100 --roi 200,150,440,330 --csv ../validation/run01.csv
```

`fri-live` connects with `IRFormat=TemperatureLinear10mK`, `PixelFormat=Mono16` (restored on
exit), leaves object parameters and measurement case untouched, prints the active case and object
parameters, then prints/logs per frame: center pixel, frame min/max/mean/std, each `--spot`
temperature, each `--roi` mean/min/max/std. The CSV has one row per frame with device and host
timestamps. Use `--simulated` for a dry run without hardware.

## Protocol

1. Same camera, same scene. Note in the table: Research Studio's range/case, emissivity,
   reflected temperature, distance, humidity, atmospheric temperature. Set the **same** values in
   the camera (Research Studio writes them to the camera; `fri-live` prints what the camera holds).
2. A stable scene is essential: a large uniform target (e.g. a matte-painted metal plate at room
   temperature, then heated on a hotplate, then near the top of the range). Wait for the camera to
   finish any NUC (the image blinks) before comparing.
3. In Research Studio place a spot at the pixel you pass to `--spot` (0-based x,y in a 640×480
   image; confirm Research Studio's indexing convention once by placing a spot at an unmistakable
   feature) and a box matching `--roi` (half-open: `x0,y0,x1,y1` covers columns x0..x1-1).
4. Run `fri-live` for ≥5 s and read both tools within the same seconds. Record the pairs below.
5. Repeat on the scenes available: room-temperature background, then warmer objects (a hand, a laptop
   exhaust, a mug of hot water). No reference hot targets exist and none are required for question A;
   the camera's three factory cases are the calibration and are never re-derived here.
6. Also record: firmware, Spinnaker version, `fri-live` commit, and the camera's own
   `ScaleLimitLow/Upper` if visible.

## Results

| Date | Case | ε | T_refl (K) | Dist (m) | RH | Scene | Location | Research Studio (°C) | FLIR Research Interface (°C) | Δ (°C) |
|---|---|---|---|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — | — | — | — | — |

Acceptance for A: |Δ| ≤ 0.1 °C for spot/center values in temperature-linear 10 mK mode (the
format's own resolution is 0.01 K; differences beyond ~0.1 °C indicate a different object
parameter, a different case, or a NUC between readings). ROI min/max/mean should match to the same
tolerance when the boxes cover identical pixels.

Until this table has rows covering at least two distinct scene temperatures, the application is
**not** validated for experimental use.
