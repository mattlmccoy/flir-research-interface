import { useEffect, useState } from "react";
import type { Preset, PresetMarker } from "../lib/presets.ts";
import type { PresetsStore } from "../lib/usePresets.ts";
import type { ApplyLine } from "../lib/presetActions.ts";

/** A name field with a submit and a cancel button. */
function NameForm({ initial = "", submitLabel, onSubmit, onCancel }: { initial?: string; submitLabel: string; onSubmit: (name: string) => Promise<void>; onCancel: () => void }) {
  const [name, setName] = useState(initial);
  const [busy, setBusy] = useState(false);
  const ok = name.trim().length > 0 && name.trim().length <= 60 && !/[/\\]/.test(name);
  const go = async () => {
    if (!ok || busy) return;
    setBusy(true);
    try { await onSubmit(name.trim()); } finally { setBusy(false); }
  };
  return (
    <div className="row">
      <input autoFocus type="text" value={name} maxLength={60} placeholder="preset name, e.g. sintering bed" aria-label="preset name"
        onChange={(e) => setName(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void go(); if (e.key === "Escape") onCancel(); }} />
      <button className="primary" disabled={!ok || busy} onClick={() => void go()}>{busy ? "…" : submitLabel}</button>
      <button className="secondary" disabled={busy} onClick={onCancel}>cancel</button>
    </div>
  );
}

/** "save current as…": asks for a name (confirming before it replaces a stored preset) and saves. */
export function SaveCurrentAs({ store, onSave, label = "save current as…" }: { store: PresetsStore; onSave: (name: string) => Promise<string>; label?: string }) {
  const [open, setOpen] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const names = store.doc?.presets.map((p) => p.name) ?? [];
  const submit = async (name: string) => {
    if (names.includes(name) && !window.confirm(`Replace the stored preset "${name}" with the current settings?`)) return;
    try { setMsg({ ok: true, text: await onSave(name) }); setOpen(false); } catch (e) { setMsg({ ok: false, text: String(e) }); }
  };
  return (
    <>
      {open ? <NameForm submitLabel="save" onSubmit={submit} onCancel={() => setOpen(false)} />
        : <div className="row"><button className="secondary" disabled={!store.doc} title={store.doc ? "Save the visible sliders, the camera settings and the palette/range as a named preset" : "presets not loaded"} onClick={() => { setMsg(null); setOpen(true); }}>{label}</button></div>}
      {msg && <div className={msg.ok ? "hint" : "errbox"} role={msg.ok ? undefined : "alert"}>{msg.text}</div>}
    </>
  );
}

interface PickerProps {
  store: PresetsStore;
  /** live: apply / save / rename / delete; playback: "apply look" only. */
  mode: "live" | "playback";
  /** Applies the preset; resolves to the lines to show (what was applied, skipped, written). */
  onApply: (p: Preset) => Promise<ApplyLine[]>;
  /** live only: builds and stores a preset from the current state; resolves to a message. */
  onSaveCurrent?: (name: string) => Promise<string>;
  /** live only: whether the current state still matches this preset (`presetMarker`). */
  marker?: (p: Preset) => PresetMarker;
}

/** Preset dropdown for the visible-camera section. Starts on the last applied preset. */
export function PresetPicker({ store, mode, onApply, onSaveCurrent, marker }: PickerProps) {
  const presets = store.doc?.presets ?? [];
  const last = store.doc?.last_applied ?? null;
  const [sel, setSel] = useState<string>("");
  const [form, setForm] = useState<"rename" | null>(null);
  const [busy, setBusy] = useState(false);
  const [lines, setLines] = useState<ApplyLine[]>([]);
  const [err, setErr] = useState<string | null>(null);
  // follow the stored list: start on last_applied, drop a selection that no longer exists
  useEffect(() => {
    if (!store.doc) return;
    if (sel && presets.some((p) => p.name === sel)) return;
    setSel(last ?? "");
  }, [store.doc]); // eslint-disable-line react-hooks/exhaustive-deps
  const chosen = presets.find((p) => p.name === sel) ?? null;

  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setErr(null); setLines([]);
    try { await fn(); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };
  const apply = () => run(async () => { if (chosen) setLines(await onApply(chosen)); });
  const del = () => {
    if (!chosen || !window.confirm(`Delete the preset "${chosen.name}"? Recordings that used it keep their values.`)) return;
    void run(async () => { await store.remove(chosen.name); setSel(""); setLines([{ text: `deleted "${chosen.name}"`, warn: false }]); });
  };
  const rename = async (newName: string) => {
    if (!chosen) return;
    await run(async () => { await store.rename(chosen.name, newName); setSel(newName); setForm(null); setLines([{ text: `renamed to "${newName}"`, warn: false }]); });
  };

  if (store.loadError && !store.doc) {
    return <div className="errbox">presets unavailable: {store.loadError} <button className="secondary" onClick={() => void store.reload()}>retry</button></div>;
  }
  const mark = mode === "live" && chosen && chosen.name === last && marker ? marker(chosen) : null;
  return (
    <div aria-label="presets">
      <div className="row">
        <select value={sel} onChange={(e) => { setSel(e.target.value); setForm(null); setLines([]); setErr(null); }} aria-label="preset" disabled={!store.doc}>
          <option value="">{store.doc ? (presets.length ? "choose a preset…" : "no presets saved") : "loading presets…"}</option>
          {presets.map((p) => <option key={p.name} value={p.name}>{p.name}{p.name === last ? " (last applied)" : ""}</option>)}
        </select>
        {mark === "applied" && <span className="hint">as applied</span>}
        {mark === "modified" && <span className="badge warn" title="The sliders, the palette/range or the camera settings differ from this preset">modified</span>}
        {mark === "camera-unknown" && <span className="badge warn" title="The camera's settings are not known (no camera connected or its info not read), so they were not compared with this preset">visible/display as applied; camera not checked</span>}
        <button className="primary" disabled={!chosen || busy} onClick={() => void apply()}
          title={mode === "live" ? "Set the sliders and the display, and write the camera settings (not while recording)" : "Save the preset's visible adjustment for this run and set the display. Camera settings are not changed."}>
          {busy ? "…" : mode === "live" ? "apply" : "apply look"}
        </button>
      </div>
      {mode === "live" && (
        <div className="row">
          <button className="secondary" disabled={!chosen || busy} onClick={() => setForm(form === "rename" ? null : "rename")}>rename…</button>
          <button className="danger" disabled={!chosen || busy} onClick={del}>delete</button>
        </div>
      )}
      {form === "rename" && chosen && <NameForm key={chosen.name} initial={chosen.name} submitLabel="rename" onSubmit={rename} onCancel={() => setForm(null)} />}
      {mode === "live" && onSaveCurrent && <SaveCurrentAs store={store} onSave={onSaveCurrent} />}
      {mode === "live" && store.lastApplied && Object.keys(store.lastApplied.thermal).length > 0 && (
        <div className="hint">Camera settings are written only when you click apply.</div>
      )}
      {lines.map((l, i) => <div key={i} className={l.warn ? "warnbox" : "hint"}>{l.text}</div>)}
      {err && <div className="errbox" role="alert">{err}</div>}
    </div>
  );
}
