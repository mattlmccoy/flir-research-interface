import { useEffect, useState } from "react";
import { api, type RfLinkSettings } from "../lib/api.ts";

/** Setup → RF link: what FLIR does when the separate T&C Power RF tool reports RF on/off. */
export function RfLinkPanel() {
  const [settings, setSettings] = useState<RfLinkSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { api.rfLinkSettings().then(setSettings).catch((e) => setErr(String(e))); }, []);

  async function save(patch: Partial<RfLinkSettings>) {
    if (!settings) return;
    const next = { ...settings, ...patch };
    setSettings(next); setBusy(true); setErr(null);
    try { setSettings(await api.saveRfLinkSettings(next)); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }

  if (!settings) return err ? <div className="errbox">{err}</div> : <div className="muted">loading…</div>;

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
      {err && <div className="errbox">{err}</div>}
    </>
  );
}
