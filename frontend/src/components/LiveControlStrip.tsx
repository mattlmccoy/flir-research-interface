import { useControlStatus } from "../lib/useControlStatus.ts";

/** Recording-page indicator for the external RF link + closed-loop control. It appears ONLY while
 *  the RF generator is actually linked to FLIR (status.engaged); otherwise it renders nothing, so
 *  the closed-loop UI is never shown unless the CXN side is engaged. Shows the last RF on/off edge
 *  and the live control loop (measured→setpoint, RF power, phase). */
export function LiveControlStrip() {
  const st = useControlStatus();
  if (!st || !st.engaged) return null;

  const rf = st.rf_link_last_event;
  const ctl = st.control_last;
  const on = rf?.state === "on";
  const rfText = rf
    ? `RF ${on ? "ON" : "OFF"}${on && rf.forward_w != null ? ` · ${rf.forward_w.toFixed(0)} W` : ""}`
    : null;
  // Live RF power comes from the control tick's forward_w (updates through the run), not the
  // one-off RF-ON edge value.
  const ctlText = ctl
    ? [
        ctl.measured_c != null && ctl.setpoint_c != null
          ? `${ctl.measured_c.toFixed(1)}→${ctl.setpoint_c.toFixed(0)}°C`
          : ctl.measured_c != null ? `${ctl.measured_c.toFixed(1)}°C` : null,
        ctl.forward_w != null ? `${ctl.forward_w.toFixed(0)} W` : (ctl.applied_w != null ? `${ctl.applied_w.toFixed(0)} W` : null),
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
