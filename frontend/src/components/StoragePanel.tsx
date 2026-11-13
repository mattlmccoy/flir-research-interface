import { useCallback, useEffect, useState } from "react";
import { api, type StorageInfo, type Volume } from "../lib/api.ts";
import { offloadHeadline, offloadRow, type OffloadDoc } from "../lib/offloadStatus.ts";

function gb(bytes: number | undefined | null): string {
  return bytes == null ? "—" : `${(bytes / 1e9).toFixed(0)} GB`;
}

/** Setup → Storage: register one external drive as the offload target, or forget it. */
export function StoragePanel() {
  const [info, setInfo] = useState<StorageInfo | null>(null);
  const [vols, setVols] = useState<Volume[] | null>(null);
  const [off, setOff] = useState<OffloadDoc | null>(null);
  const [offErr, setOffErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api.storage().then(setInfo).catch((e) => setErr(String(e)));
    api.storageVolumes().then(setVols).catch(() => setVols([]));
    api.offload().then((d) => { setOff(d); setOffErr(null); }).catch((e) => { setOff(null); setOffErr(String(e)); });
  }, []);
  useEffect(() => { refresh(); const id = setInterval(refresh, 5000); return () => clearInterval(id); }, [refresh]);

  async function register(mount: string) {
    setBusy(true); setErr(null);
    try { setInfo(await api.registerDrive(mount)); refresh(); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }
  async function forget() {
    setBusy(true); setErr(null);
    try { setInfo(await api.forgetDrive()); refresh(); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }

  async function offloadAct(fn: () => Promise<OffloadDoc>) {
    setBusy(true); setErr(null);
    try { setOff(await fn()); setOffErr(null); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }

  const drive = info?.drive ?? null;
  return (
    <>
      <div className="hint storage-scope">Totals: all collections, both volumes</div>
      <div className="kv">
        <span>Local recordings</span>
        <span className="v">{gb(info?.local.free_bytes)} free of {gb(info?.local.total_bytes)}</span>
        <span>Offload drive</span>
        <span className="v plain" style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          {drive ? (
            <>
              <b>{drive.mount}</b>
              {drive.connected
                ? <span className="badge ok">connected · {gb(drive.free_bytes)} free</span>
                : <span className="badge warn">not connected — reconnect it</span>}
              <button className="secondary" disabled={busy} onClick={forget}>forget</button>
            </>
          ) : <span className="muted">none — pick a drive below</span>}
        </span>
      </div>
      <div className="hint" style={{ marginTop: 8 }}>
        Recording always writes to local disk. Registering a drive lets you <b>move finished runs</b> to
        it (copy → verify → delete) from the experiments page to free space, and browse/play runs stored
        there. One drive at a time.
      </div>
      <div className="offload">
        <div className="row" style={{ alignItems: "center", justifyContent: "space-between" }}>
          <label className="offload-toggle">
            <input type="checkbox" checked={!!off?.enabled} disabled={busy || !off}
              onChange={(e) => void offloadAct(() => api.setOffload(e.target.checked))} />
            <b>Auto-move finished runs to the SSD</b>
          </label>
          <span className={`badge ${off == null ? "bad" : off.pending.some((p) => offloadRow(p).tone === "bad") ? "bad" : off.enabled ? "ok" : "lib"}`}>
            {offloadHeadline(off)}
          </span>
        </div>
        <div className="hint">
          {drive
            ? <>Each run records here first, then moves to <b>{drive.mount}</b> once its exports finish and nothing is recording (copy → verify → delete). If the SSD drops off or a copy fails, the run stays on this Mac and is retried.</>
            : <>Register a drive below to use this. Runs record on this Mac until then.</>}
        </div>
        {offErr && <div className="errbox">offload status unavailable: {offErr}</div>}
        {off && off.pending.length > 0 && (
          <>
            <ul className="offload-list">
              {off.pending.map((p) => {
                const r = offloadRow(p);
                return (
                  <li key={`${p.collection}/${p.name}`} className={`offload-item ${r.tone}`}>
                    <span className="offload-run"><span className="muted">{p.collection}/</span>{p.name}</span>
                    <span className="offload-state">{r.label}</span>
                  </li>
                );
              })}
            </ul>
            <div className="row">
              <button className="secondary" disabled={busy} onClick={() => void offloadAct(api.retryOffload)}
                title="clear failure counts and try every waiting run now">retry now</button>
            </div>
          </>
        )}
      </div>
      <div className="row" style={{ marginTop: 8, alignItems: "center" }}>
        <b className="hint">Detected drives</b>
        <button className="secondary" disabled={busy} onClick={refresh}>rescan</button>
      </div>
      {vols && vols.length === 0 && <div className="muted">No external drives detected. Plug one in and rescan.</div>}
      {vols && vols.map((v) => (
        <div key={v.mount} className="row" style={{ justifyContent: "space-between" }}>
          <span><b>{v.label}</b> <span className="muted">{v.mount} · {v.fstype} · {gb(v.free_bytes)} free</span></span>
          {v.is_registered
            ? <span className="badge ok">registered</span>
            : <button className="primary" disabled={busy} onClick={() => register(v.mount)}>register</button>}
        </div>
      ))}
      {err && <div className="errbox">{err}</div>}
    </>
  );
}
