# Visible camera, RTSP, and Wi-Fi: investigation (Milestone 9 groundwork)

Evidence gathered 2026-09-01 on the FLIR A70 (fw 42.0.0) with the user manual T810579 and
direct experiments. The thermal pipeline stays untouched.

**Implemented 2026-09-02 (Milestone 9 core, untested on hardware):**
`backend/flir_research_interface/visible/recorder.py` runs
`ffmpeg -rtsp_transport tcp -use_wallclock_as_timestamps 1 -i rtsp://…/avc/ch1 -map 0:v:0 -an -c copy -f mp4 visible.mp4`
next to the thermal store when the recording is started with `visible: true` (the "visible
video" checkbox in the RECORDING section). A `visible.json` sidecar holds the start/stop host
times, the redacted URL, the command and the file hash; `GET /api/experiments/{name}` exposes it
as `visible`. ffmpeg is stopped with `q` so the MP4 is finalised; if ffmpeg dies the thermal
recording continues and the status shows `visible: error`. Credentials come from `backend/.env`
(`FRI_CAMERA_HOST`, `FRI_RTSP_USER`, `FRI_RTSP_PASSWORD`); without them, or without ffmpeg, the
option reports `unavailable`.

**Verified on the A70 (2026-09-02, 8 s run `20260902_122258_m9_visible_check`):** `visible.mp4`
is a valid 1280×960 H.264 file; ffmpeg's first packet arrived 23 ms after the first thermal
frame's host timestamp. **The camera throttles the RTSP encoder while the GigE radiometric stream
is active**: measured with 6 s captures, `/avc/ch1` delivered 169 frames (≈28 fps) with the GigE
stream stopped but only 63–75 frames (≈11–12 fps) with the radiometric stream running, for every
timestamp mode tried (`-use_wallclock_as_timestamps`, native RTP, `-fflags +genpts`). So a
visible recording taken alongside thermal acquisition is a ~12 fps video, which is adequate for
"what did the sample look like" but not for frame-to-frame fusion. The measured frame count,
duration and fps are written into `visible.json` at stop. Still to do: playback of the visible
video beside the thermal image.

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

### Measured streams (2026-09-01, `fri-rtsp-check --method both`, account `rtsp`, Digest on)

| URL | Codec | Resolution | Frame rate (ffprobe) | Notes |
|---|---|---|---|---|
| `rtsp://<ip>/avc/ch1` | H.264, profile-level-id 424020 (Baseline 4.2), yuv420p | **1280×960** | ~29.25 fps | visible camera, uncropped; plus an `application/vnd.onvif.metadata` RTP track |
| `rtsp://<ip>/avc/` | H.264, profile-level-id 42401e (Baseline 3.0), yuv420p | 640×480 | ~29.97 fps | web-UI display image (follows the camera's image mode/palette); same metadata track |

Both Digest handshakes were accepted by the built-in RFC 2617 client **and** by ffmpeg 6.1
(`ffprobe -rtsp_transport tcp`), so ffmpeg is a valid RTSP stack for the recorder. Plan for
Milestone 9: `ffmpeg -rtsp_transport tcp -i <url> -c copy -f mp4 visible.mp4` (no re-encode) with
per-packet host receive timestamps, or PyAV for frame-level timestamps if needed.

### Probing the streams with credentials (`fri-rtsp-check`)

```bash
cd backend
cp .env.example .env          # then edit .env: FRI_RTSP_USER / FRI_RTSP_PASSWORD from the calibration certificate
uv run fri-rtsp-check         # probes /avc/ch1 (visible 1280x960) and /avc/ (display) with ffprobe
```

`.env` is git-ignored. The tool percent-encodes the credentials into the RTSP URL and prints
every URL with the password redacted (`rtsp://admin:***@host/...`). Passwords must never be put
in shell history, chat, logs, or the repository; if one has been exposed, change it in the
camera web UI (`http://<ip>/`).

### RTSP authentication findings (2026-09-01)

* Server: `GStreamer RTSP server`; `OPTIONS` works unauthenticated; every real path
  (`/avc/`, `/avc`, `/avc/ch1`, `/avc?ch0`, `/avc?ch1`, `/mjpg?ch1`) answers
  `401 Unauthorized` with `WWW-Authenticate: Digest realm="GStreamer RTSP Server"`; unknown
  paths answer `404`. So routing is fine and the server wants HTTP-Digest credentials.
* The web-UI **admin** account was rejected by RTSP (ffprobe handles Digest correctly).
* Manual §10.2/§10.5.5: the camera has three roles, `admin`, `user`, `viewer`; `user` and
  `viewer` are **disabled by default** and are enabled/given passwords under
  Administration → User management. Third-party notes for this family mention a video-stream
  "Authentication method" setting (Digest / Off) in the web UI — not confirmed in the manual.
* FLIR firmware release notes (KB 5907), firmware 4.45.003: "Authenticated RTSP video stream is
  now available and enabled by default." and "For disabling the RTSP authentication, go to the
  camera web interface at Settings → Video Settings and change the Authentication method from
  Digest to Off." Latest A50/A70 firmware listed there: 4.60.003 (this unit reports 42.0.0 via
  GenICam `DeviceVersion`, a different numbering; check the web UI System page).
* Both `admin` and an enabled `user` account were rejected by RTSP via ffprobe although both log
  into the web UI. Reports exist of ffmpeg failing Digest against cameras where VLC succeeds, so
  `fri-rtsp-check --method raw` now performs its own RFC 2617 Digest DESCRIBE to separate an
  ffmpeg handshake problem from a camera-side rejection.
* **Resolved (web UI, Settings → Video settings → Authentication):** the stream has a dedicated
  account, user **`rtsp`**, with its own password, independent of the `admin`/`user`/`viewer`
  web accounts. "Authentication method" offers Digest (keep it) or Off. The operator sets the
  `rtsp` password there and puts `FRI_RTSP_USER=rtsp` / `FRI_RTSP_PASSWORD=...` in
  `backend/.env`. The same page holds the camera's own recording settings (video format H264,
  30 Hz, pre/post-trigger durations) which are unrelated to our recorder.

Open items before implementing: confirm `/avc/ch1` codec/fps/latency once credentials are
available (`ffprobe rtsp://USER:PASS@<ip>/avc/ch1`, run by the user); check how the visible
camera's field of view registers to the thermal FOV (needed for any overlay); decide whether the
camera's colour thermal RTSP stream is worth recording as a preview (probably not: we render
our own from the radiometric data).

### Live preview and an RTSP hang (2026-09-02)

The live preview (`GET /api/visible/live.mjpeg`, `visible/preview.py`) runs one ffmpeg per viewer
that transcodes `/avc/ch1` to a 640 px, 8 fps MJPEG. A first version re-created the `<img>` URL on
every render, which opened a new RTSP session per thermal frame; ~40 sessions later the camera's
GStreamer RTSP server stopped answering DESCRIBE on every path (TCP 554 still accepted
connections) while GigE streaming and the web UI kept working. The operator now keeps one URL per
"show", closes the transcode when the viewer leaves, and caps the preview at 2 viewers. The RTSP
server did not recover by itself within minutes; a camera power cycle restores it.

Latency (measured 2026-09-02 after the fixes): ffmpeg runs with `-fflags nobuffer -flags
low_delay -probesize 32 -analyzeduration 0 -max_delay 0`, the operator relays from an unbuffered
pipe through a reader thread, and the page fetches the stream itself (so stopping aborts the
request and the transcode ends within ~2 s). First image ~1.2–2.3 s after the click, then
~7–9 fps. What remains is the camera's own H.264 encoder delay and GOP structure, roughly a
second behind the radiometric stream; it is a preview, not a synchronised second channel.

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
