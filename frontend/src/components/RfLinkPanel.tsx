import { useEffect, useState } from "react";
import { api, type RfLinkEvent } from "../lib/api.ts";

const RF_LINK_POLL_MS = 3000;

/** Setup → RF link: shows the last RF on/off event received from the T&C/CXN tool. Starting and
 *  stopping a recording on RF now lives in the recording panel's trigger ("on RF signal"), so this
 *  panel is status-only. */
export function RfLinkPanel() {
  const [lastEvent, setLastEvent] = useState<RfLinkEvent | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const tick = () => api.rfLinkSettings()
      .then((s) => { if (!cancelled) { setLastEvent(s.last_event); setErr(null); } })
      .catch((e) => { if (!cancelled) setErr(String(e)); });
    tick();
    const poll = setInterval(tick, RF_LINK_POLL_MS);
    return () => { cancelled = true; clearInterval(poll); };
  }, []);

  const eventLine = lastEvent
    ? `Last RF event: ${lastEvent.state === "on" ? "RF ON" : "RF OFF"}` +
      (lastEvent.state === "on" && lastEvent.forward_w != null ? ` · ${lastEvent.forward_w.toFixed(1)} W` : "") +
      ` · ${new Date(lastEvent.ts).toLocaleTimeString()}`
    : "Last RF event: none received yet";

  return (
    <>
      <div className="hint">The external RF tool reports RF on/off here. To record on RF, arm a
        recording with the <b>“on RF signal”</b> trigger in the recording panel (live page) — it
        starts on RF-on and can stop on RF-off, with pre-trigger and a safety cap.</div>
      <div className="hint">{eventLine}</div>
      {err && <div className="errbox">{err}</div>}
    </>
  );
}
