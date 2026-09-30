// Live RF / CXN overlay for the live temperature plot. The operator only exposes the latest control
// sample and RF-link edge (GET /api/control/status, polled), so this accumulates them into traces
// on the live plot's time base: each NEW sample (by its timestamp) is placed at the live time of the
// newest frame when it was seen. Polling makes it coarse (one point per poll), which is fine for
// reading RF power and setpoint against the ROI temperatures.
import { TraceBuffer } from "./plot.ts";
import { CONTROL_STYLE } from "./controlOverlay.ts";
import type { ControlStatus } from "./api.ts";

export interface LiveCtlTrace { id: number; label: string; color: string; dash: number[]; t: Float64Array; v: Float64Array; }

export class LiveControl {
  readonly rf: TraceBuffer;
  readonly setpoint: TraceBuffer;
  readonly markers: { t: number; label: string }[] = [];
  private lastCtlTs: string | null = null;
  private lastRfTs: string | null = null;

  constructor(maxPoints = 3600) {
    this.rf = new TraceBuffer(maxPoints);
    this.setpoint = new TraceBuffer(maxPoints);
  }

  /** Fold one poll into the traces at live time `t` (seconds). Returns true when anything changed. */
  ingest(st: ControlStatus | null, t: number): boolean {
    if (!st || !Number.isFinite(t)) return false;
    let changed = false;
    const c = st.control_last;
    if (c && c.ts && c.ts !== this.lastCtlTs) {
      this.lastCtlTs = c.ts;
      const w = c.forward_w ?? c.applied_w ?? null;
      this.rf.push(t, typeof w === "number" ? w : null);
      this.setpoint.push(t, typeof c.setpoint_c === "number" ? c.setpoint_c : null);
      changed = true;
    }
    const e = st.rf_link_last_event;
    if (e && e.ts && e.ts !== this.lastRfTs) {
      const first = this.lastRfTs === null;
      this.lastRfTs = e.ts;
      // the edge that was already current when the page opened is history, not a live event
      if (!first) { this.markers.push({ t, label: `RF ${e.state === "on" ? "ON" : "OFF"}` }); changed = true; }
    }
    return changed;
  }

  clear(): void {
    this.rf.clear(); this.setpoint.clear(); this.markers.length = 0;
  }

  /** RF power for the right axis (empty until a sample with power arrives). */
  rightTraces(): LiveCtlTrace[] {
    const v = this.rf.v;
    return v.some((x) => Number.isFinite(x))
      ? [{ id: -200, label: "RF power", color: CONTROL_STYLE.rf.color, dash: [...CONTROL_STYLE.rf.dash], t: this.rf.t, v }]
      : [];
  }

  /** The closed-loop setpoint on the temperature axis (empty when no loop is running). */
  leftTraces(): LiveCtlTrace[] {
    const v = this.setpoint.v;
    return v.some((x) => Number.isFinite(x))
      ? [{ id: -201, label: "setpoint", color: CONTROL_STYLE.setpoint.color, dash: [...CONTROL_STYLE.setpoint.dash], t: this.setpoint.t, v }]
      : [];
  }
}
