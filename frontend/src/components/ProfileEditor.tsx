import { useEffect, useState } from "react";
import { api, DEFAULT_PROFILE, type Profile, type ProfileField, type ProfileSuggestion } from "../lib/api.ts";

const KEY_RE = /^[a-z][a-z0-9_]{0,39}$/;
const slug = (label: string) => label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").replace(/^[^a-z]/, "f$&").slice(0, 40);

/** Setup page: the project profile — metadata fields the record panel asks for, mark buttons + hotkeys. */
export function ProfileEditor() {
  const [p, setP] = useState<Profile>(DEFAULT_PROFILE);
  const [saved, setSaved] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.profile().then(setP).catch((e) => setErr(String(e))); }, []);
  const [desc, setDesc] = useState("");
  const [sug, setSug] = useState<ProfileSuggestion | null>(null);
  useEffect(() => {
    if (!desc.trim()) { setSug(null); return; }
    const id = setTimeout(() => { api.profileSuggest(desc).then(setSug).catch(() => setSug(null)); }, 250);
    return () => clearTimeout(id);
  }, [desc]);
  const hasField = (key: string) => p.fields.some((f) => f.key === key);
  const hasMark = (label: string) => p.marks.some((m) => m.label === label);
  const addField = (f: ProfileField) => { if (!hasField(f.key)) setP({ ...p, fields: [...p.fields, { key: f.key, label: f.label, type: f.type }] }); };
  const addMark = (m: { label: string; key?: string }) => { if (!hasMark(m.label)) setP({ ...p, marks: [...p.marks, m.key ? { label: m.label, key: m.key } : { label: m.label }] }); };
  const setField = (i: number, patch: Partial<ProfileField>) => setP({ ...p, fields: p.fields.map((f, j) => (j === i ? { ...f, ...patch } : f)) });
  const setMark = (i: number, patch: { label?: string; key?: string }) => setP({ ...p, marks: p.marks.map((m, j) => (j === i ? { ...m, ...patch } : m)) });
  async function save() {
    setBusy(true); setErr(null); setSaved(null);
    try {
      const clean: Profile = { ...p, marks: p.marks.map((m) => (m.key ? m : { label: m.label })) };
      setP(await api.saveProfile(clean)); setSaved("saved on the operator; every browser and the next recording use it");
    } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }
  const badKey = p.fields.some((f) => !KEY_RE.test(f.key)) || new Set(p.fields.map((f) => f.key)).size !== p.fields.length;
  return (
    <>
      <div className="muted" style={{ marginBottom: 8 }}>The tool assumes nothing about your experiment. This profile decides which metadata fields the record panel asks for and which mark buttons (with hotkeys) appear while recording. Recordings stamp the profile name; the data format does not depend on it.</div>
      <div className="kv">
        <span>profile name</span><span className="v plain"><input type="text" value={p.name} maxLength={60} style={{ width: 220 }} aria-label="profile name" onChange={(e) => setP({ ...p, name: e.target.value })} /></span>
      </div>
      <div className="card" style={{ marginTop: 12, background: "var(--bg-deep)" }}>
        <div className="hint"><b>Profile builder</b> — describe the experiment in a few words (material, process, what heats it) and pick from the suggested fields and marks. Works offline from a built-in library; you can also skip this and add fields by hand below.</div>
        <input type="text" value={desc} placeholder="e.g. nylon PA12 powder heated by RF at 13.56 MHz" style={{ width: "100%", marginTop: 6 }} aria-label="describe the experiment" onChange={(e) => setDesc(e.target.value)} />
        {sug && desc.trim() && (
          <div style={{ marginTop: 8 }}>
            <div className="hint">{sug.matches.length ? <>recognised: {sug.matches.map((m) => <span key={m.id} className="badge ok" style={{ marginRight: 6 }} title={`matched: ${m.hits.join(", ")}`}>{m.title}</span>)}</> : "no specific application recognised — showing the general fields; try naming the material or the heat source"}</div>
            <div className="hint" style={{ marginTop: 6 }}><b>Suggested fields</b> (click to add; greyed = already in the profile)</div>
            <div className="row" style={{ marginTop: 4 }}>
              {sug.fields.map((f) => (
                <button key={f.key} className="secondary" disabled={hasField(f.key)} onClick={() => addField(f)} title={`${f.why} · from: ${f.source}`}>{f.label}</button>
              ))}
              <button className="primary" onClick={() => setP({ ...p, fields: [...p.fields, ...sug.fields.filter((f) => !hasField(f.key)).map((f) => ({ key: f.key, label: f.label, type: f.type }))] })}>add all</button>
            </div>
            {sug.marks.length > 0 && (
              <>
                <div className="hint" style={{ marginTop: 6 }}><b>Suggested marks</b></div>
                <div className="row" style={{ marginTop: 4 }}>
                  {sug.marks.map((m) => <button key={m.label} className="secondary" disabled={hasMark(m.label)} onClick={() => addMark(m)} title={`hotkey ${m.key ?? "none"} · from: ${m.source}`}>{m.label}{m.key ? <small className="muted"> {m.key}</small> : null}</button>)}
                </div>
              </>
            )}
          </div>
        )}
      </div>
      <div className="hint" style={{ marginTop: 10 }}><b>Metadata fields</b> (label shown in the form · key stored in metadata.json · type)</div>
      {p.fields.map((f, i) => (
        <div className="row" key={i}>
          <input type="text" value={f.label} placeholder="label" style={{ width: 160 }} aria-label={`field ${i + 1} label`} onChange={(e) => setField(i, { label: e.target.value, key: f.key === slug(f.label) || f.key === "" ? slug(e.target.value) : f.key })} />
          <input type="text" value={f.key} placeholder="key" style={{ width: 170, borderColor: KEY_RE.test(f.key) ? undefined : "var(--err)" }} aria-label={`field ${i + 1} key`} onChange={(e) => setField(i, { key: e.target.value })} />
          <select value={f.type} aria-label={`field ${i + 1} type`} onChange={(e) => setField(i, { type: e.target.value as ProfileField["type"] })}><option value="text">text</option><option value="number">number</option></select>
          <button className="secondary" onClick={() => setP({ ...p, fields: p.fields.filter((_, j) => j !== i) })} aria-label={`remove field ${f.label}`}>×</button>
        </div>
      ))}
      <div className="row"><button className="secondary" onClick={() => setP({ ...p, fields: [...p.fields, { key: "", label: "", type: "text" }] })}>+ field</button></div>
      <div className="hint" style={{ marginTop: 10 }}><b>Mark buttons</b> (label · optional single-key hotkey while recording)</div>
      {p.marks.map((m, i) => (
        <div className="row" key={i}>
          <input type="text" value={m.label} placeholder="label" maxLength={40} style={{ width: 160 }} aria-label={`mark ${i + 1} label`} onChange={(e) => setMark(i, { label: e.target.value })} />
          <input type="text" value={m.key ?? ""} placeholder="key" maxLength={1} style={{ width: 48 }} aria-label={`mark ${i + 1} hotkey`} onChange={(e) => setMark(i, { key: e.target.value.slice(-1).toLowerCase() })} />
          <button className="secondary" onClick={() => setP({ ...p, marks: p.marks.filter((_, j) => j !== i) })} aria-label={`remove mark ${m.label}`}>×</button>
        </div>
      ))}
      <div className="row"><button className="secondary" onClick={() => setP({ ...p, marks: [...p.marks, { label: "" }] })}>+ mark</button></div>
      <div className="row" style={{ marginTop: 10 }}>
        <button className="primary" disabled={busy || badKey || !p.name.trim()} onClick={save}>save profile</button>
        <button className="secondary" onClick={() => setP({ name: "RF heating", fields: [
          { key: "operator", label: "Operator", type: "text" }, { key: "sample_id", label: "Sample ID", type: "text" }, { key: "material", label: "Material", type: "text" },
          { key: "dopant", label: "Dopant", type: "text" }, { key: "dopant_concentration", label: "Dopant conc.", type: "text" }, { key: "rf_frequency_mhz", label: "RF freq (MHz)", type: "number" },
          { key: "rf_forward_power_w", label: "RF fwd (W)", type: "number" }, { key: "electrode_gap_mm", label: "Gap (mm)", type: "number" }, { key: "notes", label: "Notes", type: "text" },
        ], marks: [{ label: "RF ON", key: "r" }, { label: "RF OFF", key: "f" }] })} title="Load the RF heating preset (what the tool used to hard-code)">load RF heating preset</button>
        <button className="secondary" onClick={() => setP(DEFAULT_PROFILE)}>reset to default</button>
      </div>
      {badKey && <div className="warnbox">Keys must be unique, lowercase letters/digits/underscores, starting with a letter.</div>}
      {saved && <div className="hint">{saved}</div>}
      {err && <div className="errbox">{err}</div>}
    </>
  );
}
