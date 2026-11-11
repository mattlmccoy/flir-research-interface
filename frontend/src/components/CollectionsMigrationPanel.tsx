import { useEffect, useState } from "react";
import { api, type MigrationPlanDoc, type MigrationResultDoc, type StorageInfo } from "../lib/api.ts";
import { collectionNameError } from "../lib/collections.ts";
import { confirmPayload, confirmText, migrationSummary } from "../lib/migrationView.ts";

type Volume = "local" | "drive";

/** One volume: Preview (read-only plan) → "Move N runs into <target>" → confirm → result. */
function VolumeMigration({ volume, label, target, disabled }: { volume: Volume; label: string; target: string; disabled: string | null }) {
  const [plan, setPlan] = useState<MigrationPlanDoc | null>(null);
  const [result, setResult] = useState<MigrationResultDoc | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { setPlan(null); setResult(null); setErr(null); }, [target, disabled]);

  async function preview() {
    setBusy(true); setErr(null); setResult(null);
    try { setPlan(await api.migrationPlan(volume, target)); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }
  async function apply() {
    if (!plan || !window.confirm(confirmText(plan))) return;
    setBusy(true); setErr(null);
    try { setResult(await api.applyMigration(confirmPayload(plan))); setPlan(null); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }

  return (
    <div className="migration-volume">
      <div className="row" style={{ alignItems: "center" }}>
        <b>{label}</b>
        <button className="secondary" disabled={busy || !!disabled || !!collectionNameError(target)} onClick={preview}>preview</button>
        {disabled && <span className="muted">{disabled}</span>}
      </div>
      {plan && (
        <>
          <div className="hint">{migrationSummary(plan)}{plan.already_in_target ? ` · ${plan.already_in_target} already in ${plan.target}/` : ""}</div>
          {plan.busy.length > 0 && <div className="warnbox">operator is busy: {plan.busy.join(", ")}</div>}
          {plan.moves.length > 0 && (
            <ul className="migration-list">{plan.moves.map((m) => <li key={m.name}>{m.src} → {m.dst}</li>)}</ul>
          )}
          {plan.conflicts.length > 0 && (
            <div className="warnbox">Not moved (destination exists):<ul className="migration-list">{plan.conflicts.map((c) => <li key={c.name}>{c.name}: {c.reason}</li>)}</ul></div>
          )}
          {plan.unexpected.length > 0 && <div className="hint">Left untouched (not a run or collection): {plan.unexpected.join(", ")}</div>}
          {plan.moves.length > 0
            ? <button className="primary" disabled={busy} onClick={apply}>Move {plan.moves.length} runs into {plan.target}</button>
            : <div className="muted">Nothing to move.</div>}
        </>
      )}
      {result && (
        <div className={result.failed.length ? "warnbox" : "hint"} role="status">
          Moved {result.moved.length}, failed {result.failed.length}{result.skipped.length ? `, skipped ${result.skipped.length}` : ""}. Log: <code>{result.log}</code>
          {result.failed.length > 0 && <ul className="migration-list">{result.failed.map((f) => <li key={f.name}>{f.name}: {f.error}</li>)}</ul>}
        </div>
      )}
      {err && <div className="errbox">{err}</div>}
    </div>
  );
}

/** Setup → Collections: move the top-level runs of each volume into one collection. */
export function CollectionsMigrationPanel() {
  const [target, setTarget] = useState("mattmccoy");
  const [info, setInfo] = useState<StorageInfo | null>(null);
  useEffect(() => {
    const tick = () => { api.storage().then(setInfo).catch(() => undefined); };
    tick();
    const id = setInterval(tick, 5000);
    return () => clearInterval(id);
  }, []);
  const drive = info?.drive ?? null;
  const targetErr = collectionNameError(target);
  return (
    <>
      <div className="hint">
        Moves runs at the top level of a volume into a collection by renaming them in place (no copy). Preview first;
        only the runs listed are moved, a run already in the collection is never overwritten, and every move is logged.
      </div>
      <div className="row" style={{ alignItems: "center", marginTop: 8 }}>
        <span>Into collection</span>
        <input type="text" value={target} aria-label="target collection" aria-invalid={!!targetErr} onChange={(e) => setTarget(e.target.value)} style={{ width: 160 }} />
        {targetErr && <span className="bad">{targetErr}</span>}
      </div>
      <VolumeMigration volume="local" label="This Mac" target={target} disabled={null} />
      {drive && (
        <VolumeMigration volume="drive" label={drive.mount.split("/").pop() || drive.mount} target={target}
          disabled={drive.connected ? null : "drive not connected — plug it in"} />
      )}
    </>
  );
}
