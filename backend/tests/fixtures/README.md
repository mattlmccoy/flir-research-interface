# Test fixtures

`discovery_ack_redacted.bin` — a real GigE Vision GVCP DISCOVERY_ACK (256 bytes) captured from a
FLIR A70 (firmware 42.0.0) on 2026-09-01 with a raw UDP broadcast to port 3956. The 16-byte serial
number field (payload offset 216) was overwritten with `00000000`; every other byte is as received.

`stream_stall_runs.json` — frame ids and `host_timestamp_ns` (no pixel data) plus the
start/stop/annotation/frame_gap events of two real FLIR A70 runs recorded over Spinnaker on
2026-09-30: the last 742 frames of `20260930_143846_Run` (the camera was disconnected 19.4 s before
the recording was stopped, yet its manifest said `complete: true`) and the last 200 frames of
`20260930_142445_Run` (healthy: last frame 0.1 s before the stop). Copied from `thermal.zarr` and
`events.json` unchanged.

`control_reset_20260923_175956.json` — timeline frames 2000–2199 (`frame_id`, `t_s`) and control
events 60–82 (`t_utc`, `frame_id`, `forward_w`, `reverse_w`) of the real run `20260923_175956_Run`.
The camera reconnected twice mid-run: ids 9177 → 1 at t = 67.8 s and 71 → 1 at t = 83.0 s, so ids
1–71 occur twice. Copied from `thermal.zarr` and `events.json` unchanged (t_s rounded to 1 µs).

`visible_sample_20261020_144402.json` — the inputs of the visible-camera sample analysis, from the
real FLIR A70 run `20261020_144402_Run` (2026-10-20). `visible_alignment` and `rois` are copied
unchanged from its `metadata.json`. `host_t0_ns` is thermal frame 0's `host_timestamp_ns`;
`t_start_s` (25.996) is where `visible.mp4` starts on the thermal axis, the segment's
`first_frame_host_ns` minus `host_t0_ns`, rounded to 1 ms. `packets` is the `pts_time` and
keyframe flag (`K` in the ffprobe flags) of all 6,192 packets of `visible.mp4`, from
`ffprobe -select_streams v:0 -show_entries packet=pts_time,flags`. No pixel data.

`visible_sample_20261020_144402.npz` — luma (the Y plane) of that run's `visible.mp4`, cropped to the
analysis region's bounding box: the mapped `freehand_sample` ROI grown by 30 px (126×124 px at
x0 316, y0 375 of the 1280×960 frame). `crops` holds frames 3170 (368.1 s on the thermal axis),
6141–6143 (before, during and after the flash at 627.77 s) and 3–26 (the first 5 s after the
0.25 s skip of frames 0–2), in that order; `crop_frames` gives their frame indices. The crops are
the decoded values, unchanged (ffmpeg 6 `-vf extractplanes=y -fps_mode passthrough`, which gives
exactly one frame per packet; the default mode inserts a duplicate). `brightening` and `keyframe`
cover all 6,192 frames. `keyframe` is the packet flag. `brightening` is **derived from the real
video by a one-off capture script**, not stored by the camera: frame *i*'s 99.5th percentile
(`np.percentile`, linear interpolation) of `int16(luma[i]) - int16(luma[i-1])` over the region
mask pixels, where the previous frame is the previous *analysed* frame (index 3 or later). It is
NaN for frames 0–3 (frames 0–2 are skipped, frame 3 has no analysed predecessor) and is computed
for keyframes too. Check values: frames 6141, 6142, 6143 give 5, 97, 27; the region has 13,543 px.

`visible_empty_segment.mp4` — the 352 bytes the visible recorder left as `visible_001.mp4` of
`20261015_141905_Run` and as `visible.mp4` of `20261015_141026_Run` (the two files are
byte-identical, sha256 `b3ab86b6…eaffc2`), copied unchanged. It is an mp4 container (`ftyp`,
`moov` with no track, an empty `mdat`) with no video stream. `ffprobe -select_streams v:0
-show_entries packet=pts_time,flags:stream=width,height -of json` exits 0 and prints empty
`packets` and `streams`, which is what `probe` in `analysis/visible_sample_io.py` reads as "no
video packets". No pixel data.

`rf_banding_frames.npz` — real A70 frames (uint16 counts, TemperatureLinear10mK) for the RF-banding
filter: `pre_riser_rf_off` / `pre_riser_rf_off_next` (frames 42 and 43 of `20261019_120320_Run`,
RF generator at 0 W), `pre_riser_rf_on` (frame 212 of the same run, heavy diagonal banding),
`riser_rf_on` (frame 1986 of `20261019_131145_Run`, camera on the riser) and `strap_weak_banding`
(frame 1065 of `20261019_182233_Run` at 150 W after the coax strap: banding ~9 mK, under the
~28 mK camera noise). Copied from `thermal.zarr` unchanged (`ir_format` stored alongside).

`smart_roi_20261020.npz` — five real A70 frames of `20261020_144402_Run` (graphite/PA12 cube in
PA12 powder, TemperatureLinear10mK) at t = 0.0, 55.0, 274.0, 549.0 and 604.0 s (frame indices 0,
1652, 8227, 16486, 18137), cropped to the run's `freehand_sample` polygon ROI bbox + 40 px
(origin x=89, y=157; 128×127 px of the 640×480 frame). Stored as °C (`counts × 0.01 − 273.15`,
float32) with `origin`, `frame_shape`, `polygon` (frame coordinates), `indices` and `t_s`; no
over-range pixels in the crops.
