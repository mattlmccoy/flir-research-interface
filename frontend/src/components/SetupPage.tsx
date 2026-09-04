import { ProfileEditor } from "./ProfileEditor.tsx";
import { StoragePanel } from "./StoragePanel.tsx";
import { CredentialsHelp } from "./CredentialsHelp.tsx";
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
  const [forceResult, setForceResult] = useState<string | null>(null);
  async function forceIp(mac: string, f: { ip: string; subnet_mask: string; gateway: string }) {
    setBusy("forcing"); setErr(null); setForceResult(null);
    try {
      const r = await api.forceIp(mac, f.ip, f.subnet_mask, f.gateway);
      setForceResult(r.acked ? `camera acknowledged; now ${r.camera_ip ?? "?"}` : "no acknowledgement from the camera; try a power cycle");
      setDisc(await api.discovery());
    } catch (e) { setErr(String(e)); } finally { setBusy(null); }
  }
  useEffect(() => { void load(); }, []);

  const pyspinOk = sdk?.pyspin_importable === true;
  const gvcp = (disc?.gvcp_devices as Any[] | undefined) ?? [];
  const spin = (disc?.spinnaker_devices as Any[] | undefined) ?? [];

  return (
    <div className="page-body">
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
                <div className="muted">Easiest fix: re-run the one-line installer from the first-run page; it fetches Spinnaker and PySpin from the project's internal mirror. Otherwise download them from Teledyne (free account).</div>
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
        {gvcp.map((d, i) => {
          const force = d.force_ip as { ip: string; subnet_mask: string; gateway: string } | null | undefined;
          return (
            <div key={i} className={d.reachable_by_sdk ? "row" : "warnbox"}>
              <div><b>{String(d.manufacturer)} {String(d.model)}</b> fw {String(d.firmware)} at <code>{String(d.camera_ip)}</code> via {String(d.via_interface)} (host {String(d.host_ip)})</div>
              {d.problem === "no_ip_announced" && force && (
                <div>
                  <div>The camera answers from <code>{force.ip}</code> but announces no IP address (0.0.0.0), so the SDK refuses it. This happens after re-plugging the link. Assign the address it is answering from until its next reboot, or power-cycle the camera.</div>
                  <div className="row" style={{ marginTop: 6 }}>
                    <button className="primary" disabled={busy !== null} onClick={() => forceIp(String(d.mac), force)}>{busy === "forcing" ? "Assigning…" : `Force IP ${force.ip}/${force.subnet_mask}`}</button>
                    {forceResult && <span className="muted">{forceResult}</span>}
                  </div>
                </div>
              )}
              {d.problem === "wrong_subnet" && (
                <div>
                  <div>Wrong subnet: put the host adapter on the camera's subnet, then scan again.</div>
                  <pre>{(d.fix as string[]).join("\n")}</pre>
                </div>
              )}
            </div>
          );
        })}
        {spin.map((d, i) => (
          <div key={`s${i}`} className="row">
            <span>Spinnaker sees <b>{String(d.model)}</b> serial {String(d.serial)} at {String(d.ip_address)}</span>
            <button className="primary" disabled={busy !== null || !pyspinOk} onClick={() => connect("spinnaker", String(d.serial))}>Connect</button>
          </div>
        ))}
        {disc?.spinnaker_error != null && <div className="errbox">Spinnaker: {String(disc.spinnaker_error)}</div>}
      </div>

      <div className="card">
        <h2>3. Visible camera credentials (optional)</h2>
        <div className="muted" style={{ marginBottom: 6 }}>The visible camera streams over RTSP and needs the camera's RTSP user and password on the operator machine. The thermal camera needs nothing.</div>
        <CredentialsHelp open />
      </div>

      <div className="card">
        <h2>4. Project profile (metadata fields and mark buttons)</h2>
        <ProfileEditor />
      </div>

      <div className="card">
        <h2>5. Storage (offload runs to an external drive)</h2>
        <StoragePanel />
      </div>

      <details className="card" style={{ opacity: 0.8 }}>
        <summary className="hint" style={{ cursor: "pointer" }}>Developer: simulated camera (no hardware)</summary>
        <div className="row" style={{ marginTop: 8 }}>
          <button className="secondary" disabled={busy !== null} onClick={() => connect("simulated")}>Connect simulated A70</button>
          <span className="muted">Synthetic 640×480 scene used by the automated tests; not a camera.</span>
        </div>
      </details>
      {err && <div className="errbox">{err}</div>}
    </div>
  );
}
