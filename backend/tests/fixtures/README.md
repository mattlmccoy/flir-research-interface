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
