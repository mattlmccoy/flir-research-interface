# Notes: FLIR Research Interface — Session 1

## Local environment (verified 2026-09-01 by direct inspection)
- Host: macOS 26.5.2, arm64 (Apple Silicon). Rosetta 2 present (`arch -x86_64 /usr/bin/true` OK).
- Pythons: 3.14.0 (python.org), 3.14.7/3.13/3.12/3.11 (Homebrew arm64), 3.9.6 (system). ALL arm64. No x86_64 Python. No uv/pyenv/conda.
- Node 23.1.0 / npm 10.9.0. git 2.44.0. No docker.
- Spinnaker SDK 3.1.0.79 at /Applications/Spinnaker (installed Sep 8 2023; libs dated Apr 25 2023).
  - libSpinnaker.dylib.3.1.0.79 is Mach-O x86_64 ONLY (`file`).
  - PySpin wheels shipped: cp36/cp37/cp38, macosx_10_14_x86_64 only.
  - `import PySpin` fails on every installed interpreter.
  - GenTL producer at /usr/local/lib/flir-gentl (FLIR_GenTL.cti) per README.
  - Local SDK headers/examples contain NO thermal/radiometric identifiers (grep for Thermal|Radiometr|TemperatureLinear|IRFormat|Emissivity|NUC -> none).
  - Examples present: Acquisition, ChunkData, NodeMapInfo, Enumeration, ImageFormatControl, etc. (generic machine-vision).
- Network: en0 = 10.90.70.74/17 (campus LAN). No camera visible in ARP. Camera not currently attached.
- FLIR Research Studio: not installed on this Mac.
- outputs/Snap-244_20_43_46_867-0001.jpg exists but is 0 bytes (empty).

## Web research (2026-09-01)

### Spinnaker SDK support for A50/A70
- FLIR KB 4186 "Spinnaker SDK - Connecting to a FLIR A50/A70 or A400/A500/A700 image streaming camera":
  https://flir.custhelp.com/app/answers/detail/a_id/4186 — official PySpin example
  `gige_example_A400_A700.py` (downloaded to plan/reference/, 17,390 bytes). Requires "Python 3.7"
  (doc is dated) + PySpin. Steps: connect GigE Vision cam, set GenICam registers, choose
  Temperature Linear or Signal Linear (=Radiometric), convert, stream, flying-spot meter.
- Datasheet (moviTHERM mirror, FLIR REV1 01/06/2022): A70 640x480, 12 um pitch, 7.5-14 um, 30 Hz,
  fixed focus "adjustable with included focus tool", FOV 29/51/95 deg, pixel formats YUV411/MONO8/MONO16,
  "Temperature Linear 16-bit: Yes", "GigE Vision, GenICam (SFNC 2.4)", IEEE 1588 listed among protocols,
  object temperature ranges A70: -20..175 C, -20..250 C, 175..1000 C; accuracy +/-2 C or +/-2 %.
  Compressed JPEG-LS radiometric only via FLIR Atlas SDK (Advanced config) — NOT our path.
  "Dual Video Streams: No (either IR, Visual, MSX, FSX or Radiometric 16 bit)".
- User manual T810579 (A50/A70 series, en-US, downloaded plan/reference/a50_a70_manual.pdf):
  - "For Image Streaming cameras, use a GigE Vision SDK to control the camera and receive a radiometric image stream." (p.13)
  - "For Image Streaming cameras, the temperature range can also be changed over GenICam." (10.4.8)
  - NUC = offset update with internal shutter; performed at start-up, on range change, on env temp change; manual trigger possible. Auto intervals: Auto / 10 / 30 / 60 min / custom / OFF (web UI).
  - RTSP URLs rtsp://<IP>/avc/ etc. are colorized video (IR/visual/MSX/FSX) — NOT radiometric. "/ch1" = 1280x960 visual.
  - Internal temperature sensors accessible via SDK; keep < 70 C.
  - Object parameters listed: Emissivity, Reflected temperature, Distance, Relative humidity, Atmospheric temperature (web UI names).
- Spinnaker release notes (teledynevisionsolutions.com, fetched 2026-09-01):
  - Latest: 4.4.0.246 (PySpin docs online say v4.4.0.248). Deprecated Python 3.9 and older; deprecated macOS Ventura 13.2 and older; deprecated Win10.
  - "Added PySpin 3.12 support for macOS and Windows" (4.x).
  - 4.1.0.157 (MacOS): "Added support for Apple Silicon based Mac for MacOS versions 11.x to 14.x".
  - 4.1.0.172 (MacOS): "This version is for Apple Silicon Macs (tested with Sonoma). For Intel-based Macs (up to MacOS 11.6), use version 3.2."
  - 3.2.0.57: "Deprecated Intel based hardware for MacOS".
  - Thermal mentions: fixes for FLIR A400 timeout, FLIR A700 SpinView init exception (=> A400/A700 family is in Spinnaker's test matrix).
  => The locally installed 3.1.0.79 (x86_64) is NOT the right SDK for this arm64 Mac. Need Spinnaker 4.4.x macOS (Apple Silicon) + matching PySpin wheel for Python 3.10-3.12. Download requires Teledyne login (could not fetch programmatically).

### Radiometric / temperature-linear GenICam nodes (evidence)
| Node / value | Evidence |
|---|---|
| `PixelFormat` = `Mono16` | FLIR example gige_example_A400_A700.py; FLIR KB 1021; MathWorks A70 page |
| `IRFormat` enum: `TemperatureLinear10mK`, `TemperatureLinear100mK`, `Radiometric` | FLIR example (GetEntryByName exact strings); LDAQ A50 code; MathWorks A70 |
| TempLinear 10 mK: T[K] = counts * 0.01 ; 100 mK: T[K] = counts * 0.1 | FLIR KB "How do I configure my camera to stream a temperature linear signal": "Signal of 50000 will correspond to 500 Kelvin"; FLIR example subtracts 273.15 to get C |
| Conversion happens ON CAMERA using camera object parameters | FLIR KB 1021 "Temperature linear data is calculated based off of the object parameters that are set in the camera. If these are inaccurate, there is no way to change them in post-process like you can with raw data." |
| `ObjectEmissivity`, `ReflectedTemperature` (K), `AtmosphericTemperature` (K) | MathWorks A70 page (values 0.85, 298, 298) |
| `ImageMode` = "Thermal" | MathWorks A70 page |
| Radiometric-mode calibration nodes `R`,`B`,`F`,`X`,`alpha1`,`alpha2`,`beta1`,`beta2`,`J1`,`J0` | FLIR example (CFloatPtr/CIntegerPtr GetNode) — used only for host-side Signal->T formula; OUT OF SCOPE for v1 |
| DISCREPANCY: MathWorks page text says multiplier gives "°C per unit" | Contradicts FLIR KB (Kelvin) and FLIR example (-273.15). Treat Kelvin as expected; VERIFY on probe by sanity check (room-temp scene ~ 29300 counts at 10 mK). |
| UNKNOWN: node name(s) for measurement range / calibration case selection (Research Studio shows "FOL08NOF -20..250 C") | Manual says range is changeable over GenICam but names no node. Must discover from probe nodemap dump. |
| UNKNOWN: node for NUC trigger, NUC auto interval, humidity, distance, ext-optics on THIS camera | Not in any fetched source for A50/A70. Discover via probe. |
| UNKNOWN: whether IRFormat is available/writable on the "Image Streaming" (non-Advanced) config; whether 10mK is available in all ranges | Discover via probe. |
| UNKNOWN: TempLinear saturation/out-of-range encoding (0? 65535? clamped?) | Discover via probe against hot/cold targets. |

### Timestamps (evidence)
- PySpin 3.1 doc (local PySpinDoc.pdf): `Image.GetTimeStamp() -> uint64 "Gets the time stamp for the image in nanoseconds."`;
  `ChunkData.GetTimestamp()` = "Timestamp of the image included in the payload at the time of the FrameStart internal event";
  `Image.GetFrameID()`; `Image.IsIncomplete()` "transport layer received less data than it requested"; `Image.GetImageStatus()`;
  `Image.GetChunkData()` valid until `Image.Release()`.
- Teledyne CameraTimeToPCTime.py: older GEV cams use `GevTimestampControlLatch` + `GevTimestampValue`; newer use `TimestampLatch` + `TimestampLatchValue`; offset = host time - cam time/1e9. Chunk timestamp enabled via ChunkModeActive/ChunkSelector=Timestamp/ChunkEnable.
- UNKNOWN for A70: tick frequency/units of device timestamp, whether chunk data is supported, PTP (IEEE 1588 listed on datasheet). Probe must print GetTimeStamp() for 2+ frames and latch values.

### Buffer ownership
- FLIR example: `GetNextImage()` -> `IsIncomplete()` -> `GetNDArray()` -> `Release()`. Comment: "Images retrieved directly from the camera need to be released in order to keep from filling the buffer." => copy NDArray before Release.
- PySpin examples: `del cam` before `cam_list.Clear()` before `system.ReleaseInstance()`.

### Licensing
- Spinnaker README header: "confidential and proprietary information of FLIR" — do not redistribute SDK libs/examples; user installs Spinnaker runtime separately.
- FLIR gige_example script has no license header — keep out of git (plan/reference/ gitignored), cite URL.
