# Closed-Loop Thermal Control — FLIR-side Design

**Date:** 2026-09-08
**Status:** approved decisions captured; pending Matt's spec sign-off before implementation.

## Goal

Let the separate **TC-POWER / CXN** session run a closed-loop thermal controller that regulates RF
power to hold a doped PA12 part at a temperature setpoint (185 °C), using **FLIR as the honest
temperature sensor and the run recorder**. FLIR never commands RF.

## Architecture (agreed with the CXN session)

```
 TC-POWER session (owns PID + drives CXN)              FLIR operator (127.0.0.1:8000)
 ───────────────────────────────────────              ──────────────────────────────
  loop tick @ ~2 Hz:
    GET /api/live/roi-temps  ───────────────────────▶  per-ROI °C from latest acquired frame
       ◀── {live, age_ms, stale, rois:[…valid…]} ─────   (honest freshness / validity)
    control_temp = rois["circle_medium_small"].mean_c
    over_temp_guard = …max_c
    power = PID(setpoint − control_temp)               [CXN generator]  ◀── FLIR never touches
    set CXN power  ─────────────────────▶
    POST /api/control/telemetry {setpoint,power,…} ─▶  timeline mark + exports/control.csv
```

- **Loop + RF actuation live entirely in the CXN session.** FLIR is measurement + logging only.
- **Same machine, localhost, no auth** (mirrors the existing rf-link).
- The control ROI is **selected on the CXN side by name** (`circle_medium_small` = the r=20 concentric
  centre circle = the doped part; the two `_powder` circles are virgin bed). FLIR exposes **all** ROIs
  by name and hard-codes none.

## Deliverable 1 — `GET /api/live/roi-temps` (the control signal)

Per-ROI temperatures computed from `AcquisitionService.latest()` (same frame source as `/ws/frames`),
converted with the existing `counts_to_celsius`, over-range pixels excluded (same rule as
`frames.py`). Reuses the ROI logic in `analysis/series.py` — no new geometry code.

```json
{
  "live": true,
  "frame_id": 12345,
  "frame_ts": "2026-09-08T12:34:56.789+00:00",
  "age_ms": 42,
  "stale": false,
  "rois": [
    { "id": 10, "name": "circle_medium_small", "kind": "circle",
      "mean_c": 182.4, "max_c": 190.1, "min_c": 176.0, "value_c": null,
      "over_range": false, "valid": true }
  ]
}
```

Field rules (the safety contract — an unknown must never read as a healthy temperature):
- `frame_ts` is **ISO-8601** (matches the CXN telemetry timestamps for easy alignment).
- `age_ms` = now − frame host timestamp.
- **Stale/absent:** if the camera is not `ACQUIRING`, there is no frame, or `age_ms > STALE_MS`
  (~1000 ms), then `live:false` / `stale:true` and **every** ROI is `valid:false` with all temps
  `null`. Never emit a stale-but-plausible number.
- **Per-ROI over-range:** an ROI whose region is saturated/over-range → that ROI `over_range:true`,
  `valid:false`, temps `null`; other ROIs unaffected.
- `value_c` populated for **spot** ROIs (single pixel); `null` for area ROIs (use mean/max/min).
- Area ROIs report `mean_c`/`max_c`/`min_c`.

Poll model: plain GET-latest, CXN polls ~2 Hz. No long-poll/WS (their loop is pull-based).

## Deliverable 2 — `POST /api/control/telemetry` (log the loop into the run)

The CXN loop POSTs once per tick. FLIR stores exactly the keys present (all optional), and:
- while a recording is active, drops a timeline event via the existing `note_event("control", …)`
  so it renders on the playback scrubber like RF marks;
- appends a row to `exports/control.csv` (plottable against ROI temperature in playback);
- caches `app.state.control_last` for the live indicator.
- when **not** recording: accepted, ack'd, no-op (control can run before hitting record).

Accepted keys (store what's present): `ts` (ISO), `setpoint_c`, `measured_c`, `applied_w` (W, null
when advisory), `recommended_w`, `phase` (ramp|approach|soak|cool|done), `mode` (advisory|auto),
`armed` (bool), `forward_w`, `reverse_w`, `reflected_fraction`, `error_c`, `roi` (name).

## Deliverable 3 — RF trigger: verify + surface

The trigger code already matches byte-for-byte on both sides (`POST /api/rf-link/event`
`{state, forward_w, reflected_fraction, reason}`). It only fires when the CXN's FLIR-link URL is set
to `http://127.0.0.1:8000` and enabled. Work:
- **Live RF/control status strip on the recording page** (App.tsx): armed?, last RF event (ON/OFF +
  watts + time), last control telemetry (setpoint / applied_w / measured). Today this only exists in
  Setup §6, which is why it looked absent.
- **End-to-end test:** a real `POST /api/rf-link/event {state:"on"}` starts + marks a recording;
  `{state:"off"}` marks (and stops only if configured). Proves the path, not just `plan_rf_action`.

## Loss-of-signal policy (Matt's decision)

On stale/invalid FLIR, the CXN **holds 0 W with RF still ON** (its current behavior). FLIR's only job
is to make stale/invalid unambiguous (Deliverable 1). No hard-RF-OFF from FLIR. The CXN's own
protection layer independently trips RF on generator over-temp / reflected / interlock /
telemetry-timeout.

## Testing (TDD)

- **Pure, unit-tested:** per-ROI stat-on-a-frame; the freshness/validity reducer (fresh vs
  no-camera vs stale-age vs over-range → correct `valid`/`stale`/null); telemetry row assembly +
  CSV formatting.
- **Data-contract tests:** "no camera", "stale frame", and "over-range ROI" each return
  `valid:false` + null temps — never a healthy-looking value (guards the exact false-green class).
- **Integration:** telemetry POST against a real recorder writes a timeline event + control.csv row;
  rf-link event starts/marks a recording.
- **Real-data check:** run against the simulated camera (and a live A70 when available), print the
  actual `GET /api/live/roi-temps` JSON, and send it to the CXN session to conform byte-for-byte.

## Scope boundary

FLIR owns: the two endpoints, control.csv storage, the live indicator, the RF-trigger test.
Out of scope (CXN session owns): the PID, the CXN protocol, fail-safe **actuation**, and the
CXN-side gaps G1 (start the live temperature consumer) and G2 (client-side age invalidation).

## Open / follow-up

- CXN wires its temperature consumer to poll this GET (their G1) and adds the telemetry POST.
- After build: send the CXN session a live sample response; verify rf-link end-to-end with a real
  RF toggle.
