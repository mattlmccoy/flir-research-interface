import { useEffect, useState } from "react";
import { api, type ControlStatus } from "../lib/api.ts";

const POLL_MS = 2000;

/** Recording-page indicator for the external RF link + closed-loop control: the last RF on/off
 *  edge the T&C/CXN tool reported and the last control-telemetry sample it posted. Makes the RF
 *  trigger visible during a run (it was previously only in Setup → RF link). */
export function LiveControlStrip() {
  const [st, setSt] = useState<ControlStatus | null>(null);
  useEffect(() => {
    let alive = true;
    const tick = () => api.controlStatus().then((s) => { if (alive) setSt(s); }).catch(() => {});
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const rf = st?.rf_link_last_event ?? null;
  const ctl = st?.control_last ?? null;
  if (!rf && !ctl) return <span className="ctl-strip muted">RF link: waiting for events</span>;

  const on = rf?.state === "on";
  const rfText = rf
    ? `RF ${on ? "ON" : "OFF"}${on && rf.forward_w != null ? ` · ${rf.forward_w.toFixed(0)} W` : ""}` +
      ` · ${new Date(rf.ts).toLocaleTimeString()}`
    : null;
  const ctlText = ctl
    ? [
        ctl.setpoint_c != null && ctl.measured_c != null
          ? `${ctl.measured_c.toFixed(1)}→${ctl.setpoint_c.toFixed(0)}°C`
          : ctl.measured_c != null ? `${ctl.measured_c.toFixed(1)}°C` : null,
        ctl.applied_w != null ? `${ctl.applied_w.toFixed(0)} W` : null,
        ctl.phase ?? null,
      ].filter(Boolean).join(" · ")
    : null;

  return (
    <span className="ctl-strip">
      {rfText && <span className={`rf ${on ? "on" : "off"}`}><i className="dot" />{rfText}</span>}
      {ctlText && <span className="ctl">loop: {ctlText}</span>}
    </span>
  );
}
