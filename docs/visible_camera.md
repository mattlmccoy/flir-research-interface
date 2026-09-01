# Visible camera, RTSP, and Wi-Fi: investigation (Milestone 9 groundwork)

Evidence gathered 2026-09-01 on the FLIR A70 (fw 42.0.0) with the user manual T810579 and
direct experiments. Nothing here is implemented yet; the thermal pipeline stays untouched.

## 1. What the camera offers

| Path | Content | Resolution | Simultaneous with radiometric GigE stream? | Auth |
|---|---|---|---|---|
| GigE Vision, `PixelFormat=Mono16` | radiometric counts (`IRFormat` Radiometric or TemperatureLinear) | 640×480 | – (this *is* the science stream) | Spinnaker control channel |
| GigE Vision, `PixelFormat=Mono8` or `YUV422_8_UYVY`, `ImageMode` ∈ {Thermal, MSX, Visual, FSX, Macro} | the camera's **display** rendering: palette-coloured thermal, MSX fusion, or the visible camera | 640×480 (visible is downscaled) | **No.** One GVSP stream; datasheet: "Dual Video Streams: No (either IR, Visual, MSX, FSX or Radiometric 16 bit)". Verified: changing `PixelFormat`/`ImageMode` swaps the payload of the single stream. | Spinnaker |
| RTSP `rtsp://<ip>/{avc,mpeg4,mjpg}/` | same display rendering as the web UI (IR/visual/MSX/FSX, overlay optional) | 640×480 | Yes (separate server, port 554) | **401 Unauthorized** – needs the web-UI credentials from the calibration certificate |
| RTSP `rtsp://<ip>/{avc,mpeg4,mjpg}/ch1` | **uncropped visible camera** | 1280×960 | Yes | same credentials |

Experiment log (all settings restored afterwards):

* `VideoSourceSelector=Visual` alone with `Mono16` still delivered radiometric-looking counts
  (22909–22975, matching the IR frame). `Mono16` appears to be radiometric regardless.
* `ImageMode=Visual` + `Mono8` → 8-bit image, values 0–91 (dark scene); `+ YUV422_8_UYVY`
  → colour frame after `ImageProcessor.Convert(..., BGR8)`. `GetNDArray()` does **not** support
  YUV422 directly (Spinnaker error −1003); convert first.
* `ImageMode=Thermal`/`MSX` + `YUV422` → palette-coloured 640×480 frames (the camera's own
  colouring, visualization data only, never to be used as measurement).
* Manual §10.4.4: "The camera captures both thermal and visual images at the same time."
  Web UI and RTSP expose the visual; GigE exposes it only as the single stream's payload.
* Web UI at `http://<ip>/` redirects to `/login`; RTSP DESCRIBE returns 401 on every URL.

## 2. Recommendation for the application

1. **Radiometric first, always over GigE (`Mono16`).** The visible camera must never displace it.
2. **Visible video via RTSP `/avc/ch1` (H.264, 1280×960)** as a *separate subsystem*: a small
   RTSP client (ffmpeg/PyAV or OpenCV) writing `visible.mp4` next to the thermal dataset, with
   host receive timestamps per decoded frame. Synchronisation with thermal frames is by host clock
   only (RTSP/RTP timestamps are not the camera's GigE timestamp domain) — expected alignment on
   the order of tens of ms plus encoder latency, adequate for "what did the sample look like when
   it melted", not for pixel-level fusion claims.
3. **Credentials**: the RTSP/web login is per camera and lives on the calibration certificate. The
   application stores it in a local config file or OS keychain, never in git and never in URLs
   written to logs. The user enters it once in the setup UI.
4. **MSX/fusion** later, on the host, from recorded thermal + visible (brief §25). The camera's own
   MSX rendering could be recorded via RTSP `/avc/` as a convenience preview only.
5. **Not chosen**: switching the GigE stream to Visual between thermal frames (would drop
   radiometric frames and break the 30 Hz record).

Open items before implementing: confirm `/avc/ch1` codec/fps/latency once credentials are
available (`ffprobe rtsp://USER:PASS@<ip>/avc/ch1`, run by the user); check how the visible
camera's field of view registers to the thermal FOV (needed for any overlay); decide whether the
camera's colour thermal RTSP stream is worth recording as a preview (probably not: we render
our own from the radiometric data).

## 3. The antenna (Wi-Fi)

Manual §10.5.7.2: the camera radio can be **Off**, **Server mode** (camera is a hotspot at
`192.168.16.1`) or **Client mode** (joins an existing network). The datasheet lists Wi-Fi as
optional; the RP-SMA antenna is fitted on this unit.

Assessment for this project:

* Not for the radiometric stream. GigE Vision over Wi-Fi is unsupported by Spinnaker's GEV
  transport expectations and would add jitter/packet loss to a 74 Mbit/s, 30 Hz stream whose
  every frame we must account for. Keep the camera on the wired, dedicated adapter.
* Possibly useful as a management path: the camera's web UI (object parameters, NUC, range,
  RTSP settings) is reachable over Wi-Fi without touching the acquisition link, and Server mode
  gives a phone/tablet a live preview in the lab.
* Security: Server mode broadcasts an open access point with its own password; leave it **Off**
  during experiments unless needed, and never bridge it to the campus network.

Decision: leave the radio off; revisit only if a wireless preview for the lab proves useful.
