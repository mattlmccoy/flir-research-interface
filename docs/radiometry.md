# Radiometry: how a temperature number is produced

Every claim below is backed either by FLIR/Teledyne documentation or by direct introspection of
**this** camera (FLIR A70, firmware 42.0.0, lens `FOL08`, Spinnaker 4.4.0.246) on 2026-09-01
using `fri-probe`. Items still unverified are marked **UNKNOWN**. Software equivalence with
FLIR Research Studio (docs/validation.md) has **not** been demonstrated yet.

## 1. Non-negotiable rules

* FLIR's factory calibration and FLIR-supported radiometric output are the source of truth.
* No detector-count-to-temperature fit, no hard-coded coefficients, no temperatures from
  rendered or RTSP video.
* Temperature-linear output is the primary path. Host-side conversion of signal-linear
  (`Radiometric`) counts is used only as a cross-check, with the camera's own constants.

## 2. The pipeline used by the application

```
detector --factory calibration + object parameters, ON CAMERA--> 16-bit temperature-linear counts
  --GigE Vision, PixelFormat=Mono16, IRFormat=TemperatureLinear10mK--> Spinnaker Image
  --GetNDArray().copy(); Release()--> Frame.counts (uint16)
  --T_K = counts * 0.01 ; T_C = T_K - 273.15--> float32 °C   (radiometry/temperature_linear.py)
```

### Verified on this camera (probe run with `--set-temperature-linear`, 2026-09-01 18:13)

| Observation | Value |
|---|---|
| `IRFormat` entries | `Radiometric` (as found), `TemperatureLinear100mK`, `TemperatureLinear10mK` |
| `PixelFormat` entries | `Mono8`, `Mono16` (as found), `YUV422_8_UYVY`, `YCbCr411_8_Planar` |
| Frame in `TemperatureLinear10mK` | 640×480 `uint16`, min 30258, max 30394, center 30283 |
| Decoded with k = 0.01 K/count | 29.43 … 30.79 °C, center 29.68 °C (room + warm desk scene) |
| Cross-check: FLIR thermography formula on the `Radiometric` frame two minutes earlier, using the camera's own `R,B,F,J0,J1,X,alpha1,alpha2,beta1,beta2` and object parameters | center 30.23 °C, 29.94 … 31.66 °C |
| Camera's own auto-scale at the time (`ScaleLimitLow/Upper`) | 301.1 … 305.1 K = 28.0 … 32.0 °C |

Conclusion: the multiplier yields **Kelvin**, exactly as FLIR's KB and example script state
(the MathWorks page's "°C per unit" wording is wrong). The 0.5 °C spread between the two methods
is within the drift expected of two frames taken two minutes apart on an uncontrolled scene and
is not a calibration statement; the formal comparison is Research Studio (docs/validation.md).

### Documentary sources

| Claim | Source |
|---|---|
| "PixelFormat … Mono16 and IRFormat … TemperatureLinear 100mK or … 10mK"; conversion "take[s] place on the camera"; cameras include A50/A70 | FLIR KB 1021 "Temperature Linear Mode" |
| 10 mK: ×0.01; 100 mK: ×0.1; "Signal of 50000 will correspond to 500 Kelvin" | FLIR KB "How do I configure my camera to stream a temperature linear signal?" |
| Exact entry strings; `(image_data * 0.01) - 273.15`; signal-linear formula with `R,B,F,J0,J1,X,alpha1,alpha2,beta1,beta2` | FLIR `gige_example_A400_A700.py` (KB 4186) |
| "Temperature linear data is calculated based off of the object parameters that are set in the camera. If these are inaccurate, there is no way to change them in post-process like you can with raw data." | FLIR KB 1021 |

## 3. Object parameters (all present, category `ObjectParameters`)

| Node | Unit | Range | Value found |
|---|---|---|---|
| `ObjectEmissivity` | – | 0…1 | 0.95 |
| `ReflectedTemperature` | Kelvin | 0…5000 | 293.15 |
| `AtmosphericTemperature` | Kelvin | 0…5000 | 293.15 |
| `ObjectDistance` | meters | 0…10000 | 1.0 |
| `RelativeHumidity` | fraction | 0…1 | 0.5 |
| `ExtOpticsTemperature` | Kelvin | 0…5000 | 293.15 |
| `ExtOpticsTransmission` | – | 0…1 | 1.0 |
| `EstimatedTransmission` | – | 0…1 | 0.0 (read-back of the camera's own estimate) |
| `UseWindowTemperature` | enum | Off/On | Off |

Consequence: because the camera applies these before emitting temperature-linear counts, the
application must set them **before recording**, display them at all times, store them with every
experiment, and log any mid-run change with old/new values (brief §30).

## 4. Measurement range ("case") selection (category `CameraControl`)

`NumCases`=3, `CurrentCase` (RW) selects the active range, `QueryCase` (RW) selects which case
`QueryCaseLowLimit`/`QueryCaseHighLimit` (Kelvin) and `QueryCaseEnabled` describe. Enumerated:

| Case | Low | High |
|---|---|---|
| 0 | −20 °C | 175 °C |
| **1 (active)** | **−20 °C** | **250 °C** |
| 2 | 175 °C | 1000 °C |

`LensName`=`FOL08`, `Segment`=`scientific`. This is what Research Studio shows as "FOL08NOF,
−20…250 °C". Switching case triggers a NUC and the `RangeSwitchStart/End` events (§6).
**UNKNOWN:** out-of-range encoding in temperature-linear counts (clamp vs sentinel). To be
measured with a target hotter than 250 °C or by switching to case 0 and viewing a >175 °C source.

## 5. Signal-linear (`Radiometric`) mode: cross-check only

Camera exposes the constants (category `Measurement`): `R` 22474.88, `B` 1520.0, `F` 1.05,
`J0` 19896 (offset), `J1` 20.4925 (gain), `X` 0.732, `alpha1` 1.239e-8, `alpha2` 1.1095e-8,
`beta1` 3.18e-3, `beta2` 3.1802e-3 ("Calibration parameter for conversion between corrected
signal to temperature in Kelvin"). A `ChunkSelector` entry `Calibration` exists (chunk mode off
by default). The application does not convert signal-linear data for measurement; it may record
these constants as metadata and use FLIR's formula only for diagnostics.

## 6. NUC, events, frame rate

* `NUCAction` (command) performs a NUC; `NUCMode` ∈ {Off, Automatic}, found Automatic.
* Events available via `EventSelector`/`EventNotification`: `NUCStart`, `NUCEnd`,
  `RangeSwitchStart`, `RangeSwitchEnd`, `FOVSwitchStart/End`, `AcquisitionStart/End`. These let
  the recorder mark NUCs and range switches in the experiment timeline (brief §9, §21).
* `LineTrigger` can map a digital input to `ExecuteNuc`/`DisableNuc`; `CounterEventSource` can
  count `NUC` events.
* `IRFrameRate` ∈ {Rate60Hz, Rate30Hz (found), Rate15Hz, Rate7Hz, Rate4Hz}; `AcquisitionFrameRate`
  1…60 Hz, found 30. `ImageCompressionMode` description: "Radiometric framerate locked at 30 Hz".
* `ImageMode` ∈ {Thermal (found), MSX, Visual, Macro, FSX}; `VideoSourceSelector` ∈ {IR, Visual}.
  Only `Thermal` + `IR` is radiometric.

## 7. Timestamps (verified)

* `Image.GetTimeStamp()` returned e.g. 1788300782851000000 with `GevTimestampTickFrequency` =
  1 000 000 000 → **nanoseconds**, and the value is Unix-epoch-like (the camera keeps wall-clock
  time, SNTP is in its protocol list). Frame timestamps end in `000000`: **1 ms granularity**.
* `TimestampLatch` + `TimestampLatchValue` work (`GevTimestampControlLatch` absent). Two latches
  40 s apart gave camera − host = **−40.762 s** both times, so the offset is stable and can be
  measured once per session and stored. Latch round-trip on the host was ~3 ms.
* `PtpEnable`/`PtpStatus` exist (PTP disabled). Option for future multi-instrument sync.
* Per frame the recorder stores `frame_id` (`Image.GetFrameID()`), device timestamp, host
  `time.time_ns()` at receipt, and the session's measured camera↔host offset.

## 8. Frame geometry and buffers

* `Width` 640, `Height` 480, but `SensorHeight`/`HeightMax` = 483 and `OffsetY` 0…3.
  **UNKNOWN:** content of the 3 extra rows (telemetry?). The application uses the default 640×480.
* `PayloadSize` 614400 = 640×480×2 bytes. `GevSCPSPacketSize` 1444; `GevDeviceMaximumPacketSize`
  1440 on the current adapter (MTU 1500, no jumbo frames yet).
* Stream layer (TL stream node map) exposes `StreamBufferHandlingMode` {OldestFirst,
  OldestFirstOverwrite, NewestOnly, NewestFirst}, `StreamBufferCountManual`, and counters
  `StreamLostFrameCount`, `StreamDroppedFrameCount`, `StreamIncompleteFrameCount`,
  `StreamMissedPacketCount`, `StreamPacketResendRequestCount`. The recorder will read these to
  account for every frame (brief §16, §27).
* Buffer ownership: `GetNextImage()` → `IsIncomplete()` → `GetNDArray()` copied → `Release()`;
  teardown `EndAcquisition()`, `DeInit()`, `del cam`, `cam_list.Clear()`, `ReleaseInstance()`.
  A pending Python exception whose traceback references SDK objects makes `ReleaseInstance()`
  fail with "something still holds a reference"; handle SDK exceptions before teardown.

## 9. Focus and other hardware nodes

`FocusControl` exposes `FocusPos`, `AutoFocus`, `FocusDistance`, etc., and `LensConnected`=True.
The datasheet describes the A50/A70 as fixed-focus with a manual focus tool. **UNKNOWN:** whether
these nodes act on this lens. Not part of the MVP.

## 10. Remaining before the pipeline is trusted for experiments

1. Software equivalence vs Research Studio at ≥3 temperatures (docs/validation.md).
2. Out-of-range/saturation encoding (§4).
3. Behaviour of temperature-linear output during a NUC and a range switch (frame gaps? stale frames?).


## Per-ROI emissivity and reflected temperature (2026-09-02)

The camera converts radiance to temperature once, with its global `ObjectEmissivity` and
`ReflectedTemperature`. An ROI may carry its own `emissivity` (0.01–1) and `reflected_c` (°C);
its values are then re-corrected, identically in the browser (`lib/emissivity.ts`) and the
operator (`radiometry/emissivity.py`, used by the series endpoint, `roi_series.csv` and
`roi_plot.png`), with the FLIR signal model and the camera's own constants R, B, F
(`metadata.json` → `camera.calibration_constants`):

    W(T)   = R / (exp(B / T) − F)
    W_meas = ε_cam · W(T_reported) + (1 − ε_cam) · W(T_refl,cam)        (undo the camera)
    T_obj  = W⁻¹( (W_meas − (1 − ε) · W(T_refl)) / ε )                    (apply the ROI's optics)

Atmospheric transmission is taken as 1 (bench distance; the A70 estimates ≈1 at 0.44 m, 50 % RH).
The raw counts are never changed; the CSV header lists each ROI's optics
(`[emissivity=0.5, reflected_c=40]`) so a reader knows which rule produced the numbers. Without
the camera constants (no `calibration_constants` in the metadata) the per-ROI setting is ignored
and the camera's value is used unchanged. Reference check in the tests: an object at 60 °C with
ε = 0.5 viewed by a camera set to ε = 0.95 reads lower; the re-correction recovers 60.000 °C.
