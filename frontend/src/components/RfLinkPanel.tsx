import { useEffect, useState } from "react";
import { api, type RfLinkEvent, type RfLinkSettings } from "../lib/api.ts";

const RF_LINK_POLL_MS = 3000;

/** Setup → RF link: what FLIR does when the separate T&C Power RF tool reports RF on/off. */
export function RfLinkPanel() {
  const [settings, setSettings] = useState<RfLinkSettings | null>(null);
  const [lastEvent, setLastEvent] = useState<RfLinkEvent | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.rfLinkSettings().then((s) => {
      if (cancelled) return;
      setSettings({ auto_start_on_rf_on: s.auto_start_on_rf_on, stop_on_rf_off: s.stop_on_rf_off });
      setLastEvent(s.last_event);
    }).catch((e) => { if (!cancelled) setErr(String(e)); });
    // Poll only the last received event so the display updates as RF toggles fire, without
    // clobbering the toggles while the operator is changing them.
    const poll = setInterval(() => {
      api.rfLinkSettings().then((s) => { if (!cancelled) setLastEvent(s.last_event); }).catch(() => {});
    }, RF_LINK_POLL_MS);
    return () => { cancelled = true; clearInterval(poll); };
  }, []);

  async function save(patch: Partial<RfLinkSettings>) {
    if (!settings) return;
    const next = { ...settings, ...patch };
    setSettings(next); setBusy(true); setErr(null);
    try { setSettings(await api.saveRfLinkSettings(next)); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }

  if (!settings) return err ? <div className="errbox">{err}</div> : <div className="muted">loading…</div>;

  const eventLine = lastEvent
    ? `Last RF event: ${lastEvent.state === "on" ? "RF ON" : "RF OFF"}` +
      (lastEvent.state === "on" && lastEvent.forward_w != null ? ` · ${lastEvent.forward_w.toFixed(1)} W` : "") +
      ` · ${new Date(lastEvent.ts).toLocaleTimeString()}`
    : "Last RF event: none received yet";

  return (
    <>
      <div className="row" title="When the RF tool reports RF turning on, immediately start a recording here.">
        <label className="hint">
          <input type="checkbox" checked={settings.auto_start_on_rf_on} disabled={busy}
            onChange={(e) => save({ auto_start_on_rf_on: e.target.checked })} /> Auto-start recording when RF turns on
        </label>
      </div>
      <div className="row" title="When the RF tool reports RF turning off: checked stops the recording immediately; unchecked keeps it rolling so the cooldown is captured.">
        <label className="hint">
          <input type="checkbox" checked={settings.stop_on_rf_off} disabled={busy}
            onChange={(e) => save({ stop_on_rf_off: e.target.checked })} /> Stop recording when RF turns off
        </label>
      </div>
      <div className="hint">Off (unchecked) keeps recording after RF-off to capture the cooldown, instead of stopping right away.</div>
      <div className="hint">{eventLine}</div>
      {err && <div className="errbox">{err}</div>}
    </>
  );
}
