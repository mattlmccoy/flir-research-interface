# Radiometry: how a temperature number is produced

This document contains only claims backed by FLIR/Teledyne documentation or by direct
inspection of the local SDK. Anything not yet observed on **this** camera is marked
**UNKNOWN** and is blocked on the Milestone-1 probe (`fri-probe`). Nothing here has been
verified against the physical A70 yet.

## 1. Non-negotiable rules

* FLIR's factory calibration and FLIR-supported radiometric output are the source of truth.
* The application does **not** implement a detector-count-to-temperature fit, does not hard-code
  Planck/calibration coefficients, and does not infer temperature from rendered or RTSP video.
* If a conversion step cannot be tied to FLIR documentation or to nodes observed on the camera,
  development stops and the gap is recorded here.

## 2. Preferred pipeline (temperature-linear mode)

```
detector  --factory calibration + object parameters, ON CAMERA-->  16-bit "temperature linear" counts
        --GigE Vision (PixelFormat=Mono16)-->  Spinnaker Image  --GetNDArray().copy(); Release()-->
        Frame.counts (uint16)  --T_K = counts * k; T_C = T_K - 273.15-->  temperature (float32 °C)
```

with `k = 0.01 K/count` for `IRFormat = TemperatureLinear10mK` and `k = 0.1 K/count` for
`IRFormat = TemperatureLinear100mK`. Implemented in
`backend/flir_research_interface/radiometry/temperature_linear.py`.

### Evidence

| Claim | Source (fetched 2026-09-01) |
|---|---|
| A50/A70 stream "Temperature Linear 16-bit"; pixel formats YUV411/MONO8/MONO16; GigE Vision + GenICam (SFNC 2.4); 30 Hz; A70 640×480 | FLIR A50/A70 Image Streaming datasheet, REV1 01/06/2022 (moviTHERM mirror) |
| "For Image Streaming cameras, use a GigE Vision SDK to control the camera and receive a radiometric image stream." | FLIR A50/A70 user's manual T810579 (en-US), §7 |
| "To stream temperature linear, the PixelFormat should be set to Mono16 and IRFormat should be set to TemperatureLinear 100mK or TemperatureLinear 10mK." Cameras listed: Ax5, **A50, A70**, A400, A700, A3xx, A6xx, A6xxx, A8xxx. "the counts-to-temperature conversion take place on the camera" | FLIR KB 1021 "Temperature Linear Mode", <https://flir.custhelp.com/app/answers/detail/a_id/1021> |
| "TemperatureLinear 10 mK: multiply the signal by 0.01 to get correct temperature … Signal of 50000 will correspond to 500 Kelvin." 100 mK: multiply by 0.1 | FLIR KB "How do I configure my camera to stream a temperature linear signal?", <https://www.flir.com/support-center/instruments2/how-do-i-configure-my-camera-to-stream-a-temperature-linear-signal/> |
| Exact enumeration strings `TemperatureLinear10mK`, `TemperatureLinear100mK`, `Radiometric` on node `IRFormat`; `PixelFormat` entry `Mono16`; Celsius = `(image_data * 0.01) - 273.15` | FLIR example `gige_example_A400_A700.py` attached to KB 4186 "Spinnaker SDK – Connecting to a FLIR A50/A70 or A400/A500/A700 image streaming camera", <https://flir.custhelp.com/app/answers/detail/a_id/4186> (local copy: `plan/reference/`, not committed) |
| Same node names observed on an A70 through a third-party GenICam stack: `IRFormat`, `ObjectEmissivity` (0.85), `ReflectedTemperature` (298 K), `AtmosphericTemperature` (298 K), `ImageMode = Thermal`, `Mono16` | MathWorks, "Acquire and Analyze Images from FLIR A70 Thermal Infrared Camera" |
| Same node names used with PySpin on an A50 (`IRFormat`, `PixelFormat`, calibration nodes `R,B,F,X,alpha1,alpha2,beta1,beta2,J1,J0`) | LDAQ `LDAQ.flir.acquisition` (open-source, "adapted from examples provided by FLIR") |
| "Temperature linear data is calculated based off of the object parameters that are set in the camera. If these are inaccurate, there is no way to change them in post-process like you can with raw data." | FLIR KB 1021 |

### Consequence for the application

* Object parameters (emissivity, reflected temperature, atmospheric temperature, distance,
  humidity, external optics) must be **set on the camera before recording**, displayed at all
  times, and stored with every experiment. Changing them mid-recording changes the data; the
  application must timestamp and log such changes (project brief §30).
* Because the conversion is linear and documented, storing raw `uint16` counts plus the
  active `IRFormat` is lossless and sufficient; temperature is derived on load.

### Known discrepancy to resolve on hardware

The MathWorks page describes the multiplier as giving "°C per unit". FLIR's own KB and FLIR's
example script both say the product is **Kelvin** (subtract 273.15 for °C). We implement the
FLIR statement. The probe verifies it trivially: a room-temperature scene in 10 mK mode should
read roughly 29 300 counts (≈293 K), not roughly 2 000.

## 3. `Radiometric` (signal-linear) mode: out of scope for v1

In `IRFormat = Radiometric` the camera streams signal-linear counts and the host must apply
FLIR's thermography formula using per-camera calibration constants (`R, B, F, X, alpha1,
alpha2, beta1, beta2, J0, J1`, read from camera nodes) plus object parameters. FLIR's example
script shows this computation. We do **not** implement it now because:

1. Temperature-linear mode already delivers FLIR's own conversion.
2. Reproducing the formula on the host is exactly the class of work we must first validate
   against Research Studio before trusting.

Whether signal-linear frames should additionally be recorded (to allow post-hoc emissivity
changes) is an open storage question; it doubles storage and is deferred until the probe shows
the mode is available on this camera.

## 4. Object parameters

Manual names (web UI): Emissivity, Reflected temperature, Distance, Relative humidity,
Atmospheric temperature. GenICam names observed on an A70 by MathWorks: `ObjectEmissivity`,
`ReflectedTemperature`, `AtmosphericTemperature` (temperatures in Kelvin).
**UNKNOWN:** exact node names for distance, relative humidity and external optics on this
camera; their units and ranges. The probe highlights every node whose name contains
`Emiss`, `Reflected`, `Atmospher`, `Humidity`, `Distance`, `ExtOptics`, `Transmission`.

## 5. Measurement range / calibration case

Research Studio shows this camera's active calibration as approximately `FOL08NOF, -20…250 °C`.
The datasheet lists A70 object-temperature ranges −20…175 °C, −20…250 °C and 175…1000 °C. The
manual states the range "can also be changed over GenICam" for Image Streaming cameras but
names no node. **UNKNOWN:** the node(s) that list and select ranges/cases. The probe
highlights nodes containing `Case`, `Range`, `Calibrat`, `Sensor`. Do not hard-code any range.

## 6. Timestamps

* `Image.GetTimeStamp()` – "Gets the time stamp for the image in nanoseconds" (PySpin 3.1
  API reference, local `PySpinDoc.pdf`). `ChunkData.GetTimestamp()` – "Timestamp of the image
  … at the time of the FrameStart internal event".
* Camera-to-host offset: Teledyne example `CameraTimeToPCTime.py` latches the camera clock
  (`TimestampLatch` + `TimestampLatchValue`, or on older GigE models `GevTimestampControlLatch`
  + `GevTimestampValue`) and compares with `time.time()`; timestamps are divided by 1e9.
* The A50/A70 datasheet lists IEEE 1588 (PTP) among supported protocols.
* **UNKNOWN for the A70:** which latch nodes exist, the tick unit actually reported, whether
  chunk data is supported, whether timestamps are monotonic across NUC events. The probe
  executes whichever latch exists, bracketed by host `time_ns()`, and records one frame's
  `GetTimeStamp()` and `GetFrameID()`.

## 7. NUC

Manual §10.4.7 / §18.6: NUC is an offset update with an internal shutter; performed at start-up,
on range change, on ambient change; automatic intervals Auto / 10 / 30 / 60 min / custom / OFF
and manual trigger exist in the web UI. **UNKNOWN:** GenICam node names for triggering NUC,
setting the interval, and detecting a NUC in progress. The probe highlights `NUC`/`Nuc`/
`Shutter`/`Calibrat` nodes.

## 8. Buffer ownership

FLIR's examples: `GetNextImage()` → `IsIncomplete()` check → `GetNDArray()` → `Release()`, and
"Images retrieved directly from the camera … need to be released in order to keep from filling
the buffer." The probe copies the array (`np.array(..., copy=True)`) before `Release()` and the
`Frame` type stores only that copy. Teardown order follows the examples: `EndAcquisition()`,
`DeInit()`, `del cam`, `cam_list.Clear()`, `system.ReleaseInstance()`.

## 9. Out-of-range / saturation

**UNKNOWN:** how temperature-linear output encodes values outside the selected range
(clamped, 0, 65535, or flagged). Until the probe and a hot/cold target answer this, the
application must not present clamped values as valid; range warnings are mandatory (brief §42).

## 10. What the probe must show before Milestone 2 starts

1. Device identity (model, serial, firmware, IP, MAC).
2. Full device / TL-device / TL-stream node maps (`probe_report.json`).
3. Whether `IRFormat` exists, its entries and current value; whether `PixelFormat` offers `Mono16`.
4. Range/case nodes; object-parameter nodes; NUC nodes; timestamp latch nodes.
5. One frame: pixel format, bits/pixel, shape, `GetTimeStamp()`, `GetFrameID()`, min/max/center counts.
6. If already in temperature-linear mode: the derived center temperature, for a plausibility check.
