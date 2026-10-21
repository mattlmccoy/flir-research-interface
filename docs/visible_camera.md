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

**Time alignment (2026-09-30).** Playback places each visible segment on the thermal clock at
(its first frame's host arrival − thermal frame 0's host arrival), `visible_timeline[].t_start_s`
(`playback/visible_timing.py`). Before, it assumed visible t=0 = thermal t=0, which was 4 s off on
every armed run (pre-trigger) and 24 s off on `20260928_193907_Run` (3 failed RTSP opens). The
first-frame host arrival is `segments[].first_frame_host_ns` in `visible.json`, estimated from
ffmpeg `-progress` as min(read time − `out_time`) (`visible/progress.py`); runs recorded before it
fall back to the ffmpeg launch (`started_host_ns`, `anchor: "launch"`). Measured on the A70 (two
20 s captures): the first frame arrives **1.08 s** after the launch, the lag this removes; with a
local source and injected connect delays the estimate was within 4 ms of the true first byte. Not
removed: the camera's encode + network latency before a frame arrives (the thermal frames' GigE
latency is milliseconds). Playback and export also skip the first 0.25 s of each file, whose frame 0
is sometimes torn (7 of 18 runs).

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

## 4. Exposure control and post-run sample analysis (2026-10-20)

On `20261020_144402_Run` (the reference run below) the white PA12 powder is clipped for the whole
video: the right half of the powder sits at exactly 255 and the left half at 245-254. The camera's
auto-exposure presumably meters the dark cage and metal and over-exposes the powder. The wanted
uses of the visible camera were spotting sparks or arcs at the sample and watching the doped part
densify and slump.

### The visible exposure cannot be set (checked 2026-10-20, firmware 4.45.003, reading only)

* **GenICam:** the 2026-09-01 dump has 249 device nodes; none controls the visible camera's
  exposure.
* **ONVIF:** the client was initialised with the `fliruser` account. The imaging service offers
  Focus only, on both `video0` (IR) and `video1` (Visual).
* **REST API and web UI:** no exposure, brightness or backlight control, including in the service
  screen's JavaScript (5 bundles). `/api/image/adjustment` is the IR display scaling, not the
  visible camera.
* **Resource tree:** `/prod/res/` answers while `httpResource` is on. `.system.vcam` holds
  `active`, `flash`, `fov`, `model` (OV5640), `test` and `torch`; there is no exposure entry. Leave
  `httpResource` off: it allows unauthenticated reads.
* **SSH:** the sensor's exposure is set inside the camera's Linux, reachable only through an
  unpublished SSH login. Out of scope. A FLIR support request and a second camera were ruled out by
  the operator.

What the clipped video still holds, measured on the reference run (6,192 frames): the sample is well
exposed (mean luma of its dark pixels 107.6 in the first analysed frame) and its outline changes
over the run. The powder is unrecoverable: contrast-stretched, it shows only a lighting gradient
and compression blocks.

### What the post-run analysis writes

`analyse_visible_sample` (`backend/flir_research_interface/analysis/visible_sample_run.py`) reads
`visible.mp4`, the visible-to-IR alignment and the ROIs, and writes only into the run's `exports/`
folder. It never touches `thermal.zarr`, `visible.mp4`, `metadata.json` or the camera. It runs in
the post-stop export job (step "visible sample analysis", after the run summary and before the
thermal preview video) and again in the derived-files regenerate job; a failure is logged and never
blocks Stop. Both ffmpeg calls have time limits, because the job holds the run's render lock, which
the media export, the offload move and the range scan also wait on: the decode is killed after
120 s without output (`DECODE_STALL_S` in `visible_sample_io.py`) and the close-up encode after
max(300 s, 2 x the segment's duration) (`CLOSEUP_MIN_TIMEOUT_S` and `CLOSEUP_TIMEOUT_FACTOR` in
`visible_sample_run.py`). The run is then `failed` with a reason that contains `timed out`; ffmpeg
is gone and no `.part` file is left. The reference run needs 4 s for the close-up.

| File | Content |
|---|---|
| `visible_sample.json` | Always written. `status` (`ok`, `skipped`, `failed`) and `reason`; for `ok` also the inputs (sample and bed ROI, alignment `saved_utc` / `rmsPx`, `threshold`, `dark_rule`, `margin_px`, flash rule and `flash_threshold`), `coverage`, `segments` (per file: `t_start_s`, `anchor`, `frames_analysed`), `missing`, `empty`, `events`, `files`. A skipped or failed run keeps only `status`, `reason`, `software`, `files`: nothing was analysed, so there is no coverage block to misread. |
| `visible_sample.csv` | One row per analysed frame: `t_s` (thermal clock), `segment`, `frame` (index in its file), `keyframe`, `sample_dark_px`, `sample_mean_luma`, `bed_clipped_frac`, `brightening` (empty on keyframes). |
| `visible_sample_plot.png` | Four panels on the thermal time axis: RF forward power; sample ROI max and mean (°C, with the 250 °C case limit); `sample_dark_px` with a 31-frame rolling median; `brightening`. Flash events are drawn as vertical lines labelled with the peak value. |
| `visible_sample_closeup.mp4` | A 3x crop around the sample with one fixed contrast stretch (luma 58-250 on the reference run). It holds every analysed frame at its time in `visible.mp4` (so it starts at the first analysed frame, not at 0), without B-frames. Later segments get `_001`, `_002`, ... |

The sample is the ROI whose name contains "sample" (smallest wins). Reasons for `skipped`: `no visible
video`, `no visible alignment`, `no sample ROI (name containing 'sample')`, `ffmpeg not found`,
`ffprobe not found`, `visible alignment is invalid`, `sample ROI maps outside the visible frame`.
Segment files that cannot be read are listed and the other segments analysed: `missing` names the
files `visible.json` lists that are not on disk; `empty` names files on disk with nothing to analyse,
either no video packet (the recorder leaves a 352-byte mp4 with no track when the camera never
delivered a frame: `20261015_141026_Run/visible.mp4`, `20261015_141905_Run/visible_001.mp4`) or every
frame inside the 0.25 s start-up skip. Neither kind gets a close-up. When no segment has a frame to
analyse the run is `skipped` with `no visible video`. Each segment's `anchor` says what its
`t_start_s` is measured from: `first_frame` (the arrival of its first frame), `launch` (the ffmpeg
launch, for recordings made before 2026-09-30; it precedes the first frame by the RTSP connect time,
so the visible times run about 1.1-1.5 s early on the thermal axis) or `relative` (no thermal frame to
anchor to). The status line under the exports says so when any segment is not `first_frame`.
`GET /api/experiments/{name}` returns the JSON as `visible_sample`; playback draws the flash events
as marks on the timeline, reachable with the existing ◆◀ / ▶◆ buttons, and shows `status` and `reason`
beside the export files. Events are not written into `events.json`.

Method: the analysis region is the sample outline mapped into the visible frame through the
alignment, grown by 30 visible px. "Dark" means luma **strictly below** the run's threshold, one
Otsu value chosen from the first 5 s of analysed frames and then held fixed, so every frame is
judged by the same rule and the counts stay comparable. That does not make the count immune to
exposure: a global brightening lifts pixels that sat just below the threshold out of "dark", and
`sample_dark_px` falls without the sample changing. Check `sample_mean_luma` and `bed_clipped_frac`
before reading a change in `sample_dark_px` as slump. `brightening` is the 99.5th percentile of
(luma - previous frame's luma) over the region. A non-keyframe is flagged when `brightening >= max(15, median + 6 x
max(MAD, 1))` over the run's non-keyframe values; flagged frames within 1.0 s form one event.

### Reference run `20261020_144402_Run` (run on 2026-10-21, `visible.mp4` sha256 `c61f66fc...`)

| Item | Result |
|---|---|
| Status, threshold | `ok`, 178; `flash_threshold` 15 (median 1.0 and MAD 1.48 leave the floor binding) |
| Start-of-run dark area | 1,095 px (mean of the first 5 s, 24 frames; 1,100 in the first frame) |
| Coverage | 6,189 frames analysed (the first 3 are skipped), 26.48-632.57 s, 61 gaps over 0.3 s adding up to 21.51 s uncovered (`uncovered_s`; the longest gap is 0.84 s, `longest_gap_s`) |
| Event 1 | 553.95-554.06 s, 2 frames, peak +20 at frame 5303 |
| Event 2 | 615.66-615.85 s, 2 frames, peak +19 at frame 6005 |
| Event 3 | 627.77-629.41 s, 7 frames, peak +97 at frame 6142 |
| 413.3-414.0 s | no event: the largest `brightening` in the window is +5; the 413.65 s decoding glitch (a band of the image shifted sideways) reads 0.0, and the frame at 413.84 s is a keyframe, whose `brightening` is left empty |
| Run time | 15.8 s on an Apple M2 Pro for 606.6 s of video, 4.05 s of it the close-up encode (the rest is decoding and measuring, the plot, which re-reads the thermal store, and probing) |

The events line up with the thermal record: the sample ROI's max jumps at about 553 s and 615 s,
and the 627.77 s event follows the max reaching 250 °C. The two small events are 4-5 levels above the
15-level floor. A noisier run raises the threshold: at a median of 1.0, a MAD above about 3.2 puts
it over +20 and drops events of that size. The effective threshold is written to every JSON for
that reason.

### Limits

* **The powder is unrecoverable** and no exposure setting is reachable (above). Nothing here shows
  powder state.
* **Flash detection ignores H.264 keyframes.** The encoder's periodic refresh shifts brightness, so
  `brightening` is left empty on keyframes (412 of the 6,189 analysed frames on the reference run).
  A flash that lands on a keyframe is not flagged.
* **The visible stream is about 10 fps with gaps.** `visible.json` records 10.2 fps for the
  reference run (the camera throttles the stream while the radiometric stream runs, see the
  2026-09-02 verification at the top of this file), and 61 gaps exceed 0.3 s, 21.5 s of the 606 s
  the frames span. A flash shorter than the gap before or after one frame can be missed; two of the
  three reference events are only two frames long.
* **A "flash" is not proof of an arc or a spark.** It is a brightening in the sample region seen in
  one or a few frames; the cause needs the thermal and RF record. "0 flashes" is only meaningful
  with the coverage next to it: a run that could not be analysed says `skipped` or `failed` and
  never reads as zero.
* **Only the sample region is watched.** Flashes at the cage, electrodes or cables are not looked
  for.

## 5. Software adjustments, full-range display and presets (2026-10-21)

The camera's exposure cannot be set (section 4), so the app adjusts the picture itself. Everything
here changes how the video is drawn or analysed. `visible.mp4`, `thermal.zarr` and every radiometric
number stay as the camera sent them, and `metadata.json` is written only when a recording starts.
Software cannot recover pixels the camera stored as 255: they stay flat. The adjustment helps with
the near-white, mid and dark areas (sample, cage, electrodes).

### The adjustment

Three numbers: `exposure_ev` (-3 to +3, neutral 0), `brightness` (-0.5 to +0.5, neutral 0) and
`contrast` (0.25 to 4, neutral 1). For a value `x` in [0, 1]:

    slope = contrast * 2**exposure_ev
    intercept = 0.5 - 0.5 * contrast + brightness
    y = clip(slope * x + intercept, 0, 1)        (uint8 output rounded to nearest)

The browser applies it with an SVG `feComponentTransfer` (`type="linear"`, R, G and B,
`color-interpolation-filters="sRGB"`), not CSS `brightness()` / `contrast()`, which cannot express
the offset. Python (`analysis/visible_adjust.py`) uses the same slope and intercept for the media
export and the analysis; `frontend/src/lib/visibleAdjust.ts` is the browser twin, and a parity test
checks both against the same table.

* **Where:** exposure, brightness and contrast sliders in the visible-camera panel for the live
  preview, and the same sliders in the visible panel in playback.
* **Live:** the values are kept in the browser like the other view settings and are stamped into the
  next recording's `metadata.json` as `visible_adjust` (`exposure_ev`, `brightness`, `contrast`,
  `preset`, `based_on`). `preset` is the last applied preset's name only when the sliders still equal
  that preset's; otherwise `preset` is null and `based_on` holds the name.
* **Playback:** the run shows, in this order, `visible_adjust.json` in the run folder (what the
  operator last saved for this run), else the `visible_adjust` stamp in `metadata.json`, else
  neutral (runs recorded before 2026-10-21 have neither and show neutral). Moving a slider saves the
  sidecar (`PUT /api/experiments/{name}/visible-adjust`); "reset to as-recorded" deletes it
  (`DELETE`, same route). The sidecar travels with the run when it is offloaded
  (`storage.MUTABLE_PATHS`).
* **Media export:** a clip that includes the visible video uses the run's effective adjustment.

### Full range: what the camera sends and what a browser shows

The visible stream is full-range luma (Y spans 0-255) but carries no range tag. ffmpeg's default
conversion and browsers read an untagged H.264 stream as limited range (16-235), which shows every
value from about 235 up as the same white; that premise is the reason for the copy below.

Measured on `20261020_144402_Run/visible.mp4` (2026-10-21), the Y plane of 10 frames at 60, 120, ...,
600 s, decoded without a range conversion:

| Measure | Value |
|---|---|
| Y range in every one of the 10 frames | 0 to 255 |
| Pixels at 236-254 | 1.52 % of all 10 frames (per frame 1.40-1.64 %) |
| Pixels at 255 | 0.83 % (per frame 0.69-0.98 %) |
| Pixels at 235 or above | 2.4 % (per frame 2.32-2.46 %) |
| Pixels below 16 | 0.02 %, none at 0 |
| `color_range` (ffprobe, `visible.mp4`) | not reported (unknown); the stream is `yuv420p`, 1280x960 |

The 1.5 % at 236-254 is the near-white detail that a limited-range reading discards before any
adjustment. The analysis already read raw Y; the display paths now do too: the live MJPEG transcode
(`visible/preview.py`) and the media-export frame extraction (`analysis/visible_overlay.py`) use
`in_range=full`, and playback plays the copy below.

### The full-range copy (`exports/visible_full_range.mp4`)

Playback serves `exports/visible_full_range.mp4` (`visible_001_full_range.mp4`, ... per segment), made
the first time the video is requested by `ffmpeg -c copy -bsf:v h264_metadata=video_full_range_flag=1`
(`visible/full_range.py`, `full_range_copy`). It is a stream copy, so the picture is not re-encoded.
The response carries `X-Visible-Range`: `full` for the copy, `raw-untagged` when ffmpeg is missing or
the build failed; in that case the raw file is played and the panel says "visible video shown without
range correction", never silently looking fixed. The copy is rebuilt when it is older than its
source and can be deleted at any time.

Measured on the reference run with ffmpeg 6 (2026-10-21):

* `ffprobe` of the copy: `color_range=pc`, `pix_fmt=yuvj420p`, 1280x960; `visible.mp4` itself is
  untouched (sha256 `c61f66fc...511c32` before and after).
* Packets: 6,192 in both files. Presentation and decode timestamps and keyframe flags are identical
  packet for packet.
* Packet sizes: 412 packets differ, each by exactly +2 bytes, and all 412 are keyframes (413 keyframes
  in all; the first one is unchanged). Cause: the bitstream filter rewrites the in-band SPS. The
  sum of packet sizes rises from 77,415,228 to 77,416,052 bytes.
* Decoded pixels: an MD5 over every decoded frame, without a pixel-format conversion, is the same
  for both files.
* Cost: the file is 77,494,109 bytes, against 77,493,283 for `visible.mp4`; building it took 0.9 s
  on the SSD. Budget the same disk space as the video again, per run that is opened.

Do not feed the copy to a tool that converts it to a limited-range format and expect the original
values: `-pix_fmt yuv420p` on the copy maps 0-255 into 16-235.

### Analysis on the adjusted video

"also analyse the adjusted video" in the Export section (off by default; remembered in the browser;
disabled while the run's adjustment is neutral) adds a second analysis to the derived-files
regenerate (`/export/derived?visible_adjusted=true`). The post-stop automatic analysis stays raw.

* **Files:** `exports/visible_sample_adjusted.{csv,json,png}` and
  `visible_sample_adjusted_closeup.mp4` (`_closeup_001.mp4`, ... per segment). The raw files are
  never touched by it, and a regenerate without the box ticked does not remove the adjusted ones.
* **What is adjusted:** the luma is mapped before the threshold, `sample_dark_px`,
  `sample_mean_luma`, `brightening` and the close-up. `bed_clipped_frac` always uses raw luma: it
  reports what the camera clipped, which an exposure cut would otherwise hide.
* **JSON:** the same fields as the raw result plus `adjust` (`exposure_ev`, `brightness`,
  `contrast`, `source`: `sidecar` or `recorded` when the app wrote it). The status line under the
  exports reads "Visible sample (adjusted: exposure ... EV, brightness ..., contrast ...)" and adds
  "; sliders changed since" when the run's sliders no longer match the ones it used.
* **Marks:** the raw result stays the default and is the one that draws the flash marks on the
  timeline.
* **The flash rule is not rescaled.** The 15-level floor applies to the adjusted luma, so a
  contrast or exposure cut (slope below 1) can hide a flash that the raw analysis flags, and a boost
  can clip one. The reference run shows it.

Reference run, `{exposure_ev: -1, brightness: 0, contrast: 1.4}` (slope 0.7, intercept -0.2), run on
2026-10-21, no sidecar written, the adjustment passed to `analyse_visible_sample(..., adjust=...)`:

| Item | Raw | Adjusted |
|---|---|---|
| Threshold (Otsu on the first 5 s) | 178 | 74 (0.7 x 178 - 51 = 73.6) |
| Close-up stretch | 58-250 | 0-250 |
| Frames analysed, coverage | 6,189, 26.48-632.57 s, 61 gaps over 0.3 s | identical |
| `sample_dark_px`, first 5 s mean / run median | 1,095.4 / 1,094 | 1,095.4 / 1,094 |
| Median `sample_mean_luma` | 107.9 | 24.8 |
| `bed_clipped_frac` | min 0.0018, median 0.319, max 0.391 | all 6,189 values identical to raw |
| Events | 3: +20 at 553.95 s, +19 at 615.66 s, +97 at 627.77 s (7 frames) | 1: +64 at 627.77-628.49 s (4 frames, frame 6142) |
| `brightening` at the two small events (frames 5303, 6005) | +20, +19 | +14, +13: under the 15 floor, so not flagged |
| Close-up | 378 x 378, 6,189 frames | 378 x 378, 6,189 frames |
| Run time (Apple M2 Pro) | 15.8 s | 34.8 s (close-up encode 5.2 s; the plot, which re-reads the thermal store from the SSD, 25.9 s, against 9.4 s for the raw run) |

The dark count does not change because the map is monotonic and the threshold moves with it. The
small events were two frames long and only 4-5 levels above the floor in raw luma, so a slope of 0.7
loses them; the 627.77 s event survives. Read an adjusted result as "what the picture on screen
shows", not as a replacement for the raw one.

### Presets

A preset is one named setup: the visible adjustment, the thermal camera settings and the thermal
display settings (palette and range).

* **What it holds:** `visible_adjust` (the three numbers); `thermal` (only the camera's writable
  nodes from `camera/controls.py` `WRITABLE_NODES`, in the camera's own units: kelvin, metres,
  fractions, `CurrentCase`, `NUCMode`, `IRFrameRate`; a node whose value was not readable is left
  out and the dialog says which); `display` (palette, and `auto` or a locked min/max range in
  degrees C); `saved_utc`. Recordings store the values, not a reference, so editing or deleting a
  preset never changes how an old run is described.
* **Where it is stored:** `presets.json` in the calibration folder beside the experiments root
  (`<experiments_root>/../calibration/presets.json`, next to `profile.json`), on the operator, so
  every browser sees it. Writes are atomic; a damaged file reads as no presets and is copied to
  `presets.json.corrupt` before the next save replaces it. The file also records `last_applied`.
  API: `GET /api/presets`, `PUT` and `DELETE /api/presets/{name}`, `POST .../rename` and
  `POST /api/presets/last-applied`.
* **Apply (live):** sets the sliders and the display, then writes the thermal block through
  `POST /api/camera/parameters`, one node per request with `CurrentCase` last, and lists what was
  written and what was not (the writes are not atomic). The confirmation warns that changing the
  measurement case triggers a NUC and a range switch. A node the camera no longer offers or an enum
  value outside its `enum_options` is refused with a reason and nothing is written.
* **Never automatic:** camera settings are written only when the operator clicks apply, never at
  start-up (a browser with nothing stored starts from the last applied preset's visible and display
  parts only), and never while a recording runs: then only the visible and display parts are applied
  and the message says the camera settings were skipped. A recording started during the writes stops
  them (the operator answers 409).
* **Apply look (playback):** writes the preset's visible part into this run's `visible_adjust.json`
  and sets the display. It never touches the camera and playback cannot save presets.

### Not tested on hardware

Everything above was checked with the simulated camera, unit tests and the reference run's files. Not
yet run against the real A70:

* the live-preview sliders on the real MJPEG preview (and `in_range=full` on the live transcode);
* the `visible_adjust` stamp in a real recording (`metadata.json` written by a real start, and
  through an armed start);
* applying a preset's thermal part to the real camera (the write order, the NUC warning, a
  `CurrentCase` change, and the refusal while recording).

Run these when the rig is available. The reference-run numbers above were measured on a finished
recording only.
