import { useEffect, useState } from "react";
import { api } from "../lib/api.ts";

type Any = Record<string, unknown>;

export function SetupPage({ onConnected }: { onConnected: () => void }) {
  const [sdk, setSdk] = useState<Any | null>(null);
  const [disc, setDisc] = useState<Any | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setErr(null);
    try { setSdk(await api.sdk()); } catch (e) { setErr(String(e)); }
  }
  async function discover() {
    setBusy("discovering"); setErr(null);
    try { setDisc(await api.discovery()); } catch (e) { setErr(String(e)); } finally { setBusy(null); }
  }
  async function connect(backend: string, serial?: string) {
    setBusy("connecting"); setErr(null);
    try { await api.connect(backend, serial); onConnected(); } catch (e) { setErr(String(e)); } finally { setBusy(null); }
  }
  useEffect(() => { void load(); }, []);

  const pyspinOk = sdk?.pyspin_importable === true;
  const gvcp = (disc?.gvcp_devices as Any[] | undefined) ?? [];
  const spin = (disc?.spinnaker_devices as Any[] | undefined) ?? [];

  return (
    <div className="setup">
      <div className="card">
        <h2>1. Camera SDK on this machine</h2>
        {!sdk && <div className="muted">checking…</div>}
        {sdk && (
          <>
            <div className="kv">
              <span>Machine</span><span className="v">{String(sdk.system)} {String(sdk.machine)} · Python {String(sdk.python_tag)}</span>
              <span>PySpin importable</span><span className="v">{pyspinOk ? `yes (${String(sdk.pyspin_detail)})` : "no"}</span>
            </div>
            {!pyspinOk && (
              <div className="warnbox">
                <div><b>{String(sdk.sdk_artifact_hint || sdk.reason)}</b></div>
                <div className="muted">Local copy: {String(sdk.pyspin_local ?? "not found")} · looked in {(sdk.pyspin_search_dirs as string[] | undefined)?.join(", ")}</div>
                <ol>{(sdk.steps as string[] | undefined)?.map((s, i) => <li key={i}><code>{s}</code></li>)}</ol>
                <div className="muted">The FLIR license does not allow this application to ship Spinnaker; download it from Teledyne with a free account.</div>
              </div>
            )}
          </>
        )}
      </div>

      <div className="card">
        <h2>2. Find the camera</h2>
        <div className="row">
          <button className="primary" onClick={discover} disabled={busy !== null}>{busy === "discovering" ? "Scanning…" : "Scan network"}</button>
          <span className="muted">Raw GigE Vision discovery on every adapter, then Spinnaker.</span>
        </div>
        {disc && gvcp.length === 0 && spin.length === 0 && <div className="errbox">No camera answered. Check PoE power, cable, and that the adapter link light is on.</div>}
        {gvcp.map((d, i) => (
          <div key={i} className={d.reachable_by_sdk ? "row" : "warnbox"}>
            <div><b>{String(d.manufacturer)} {String(d.model)}</b> fw {String(d.firmware)} at <code>{String(d.camera_ip)}</code> via {String(d.via_interface)} (host {String(d.host_ip)})</div>
            {!d.reachable_by_sdk && (
              <div>
                <div>Wrong subnet: put the host adapter on the camera's subnet, then scan again.</div>
                <pre>{(d.fix as string[]).join("\n")}</pre>
              </div>
            )}
          </div>
        ))}
        {spin.map((d, i) => (
          <div key={`s${i}`} className="row">
            <span>Spinnaker sees <b>{String(d.model)}</b> serial {String(d.serial)} at {String(d.ip_address)}</span>
            <button className="primary" disabled={busy !== null || !pyspinOk} onClick={() => connect("spinnaker", String(d.serial))}>Connect</button>
          </div>
        ))}
        {disc?.spinnaker_error != null && <div className="errbox">Spinnaker: {String(disc.spinnaker_error)}</div>}
      </div>

      <div className="card">
        <h2>3. No hardware? Use the simulated camera</h2>
        <div className="row">
          <button className="secondary" disabled={busy !== null} onClick={() => connect("simulated")}>Connect simulated A70</button>
          <span className="muted">Synthetic 640×480 scene: 25 °C background, hotspot ramping to 200 °C over 60 s.</span>
        </div>
      </div>
      {err && <div className="errbox">{err}</div>}
    </div>
  );
}
