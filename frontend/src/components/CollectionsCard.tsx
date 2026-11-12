import { useState } from "react";
import { api, type CollectionsDoc, type UsersDoc } from "../lib/api.ts";
import { collectionNameError, renameError } from "../lib/collections.ts";
import { collectionRows, currentUser } from "../lib/users.ts";
import { CollectionsMigrationPanel } from "./CollectionsMigrationPanel.tsx";

/** Setup → Collections: every collection, who uses it and where it lives; record into one, add one,
 *  or rename one (on this Mac and the SSD, for everyone). The loose-run sorter sits underneath.
 *  The same operator calls as the top-bar user menu, so both always agree. */
export function CollectionsCard({ collections, users, locked, onCollections, onUsers }: {
  collections: CollectionsDoc | null; users: UsersDoc | null; locked: boolean;
  onCollections: (d: CollectionsDoc) => void; onUsers: (d: UsersDoc) => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);  // collection being renamed, or "" = new
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (!collections) return <div className="muted">loading collections…</div>;
  const me = currentUser(users);
  const rows = collectionRows(collections, users);
  const draftErr = draft === "" || editing === null ? null
    : editing === "" ? collectionNameError(draft) ?? (rows.some((r) => r.name === draft) ? `${draft} already exists` : null)
    : renameError(editing, draft, collections);

  const stop = () => { setEditing(null); setDraft(""); };
  async function act(fn: () => Promise<void>) {
    setBusy(true); setErr(null);
    try { await fn(); stop(); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }
  const record = (name: string) => act(async () => { onCollections(await api.selectCollection(name)); onUsers(await api.users()); });
  const submit = () => {
    if (!draft || draftErr || busy || editing === null) return;
    const old = editing;
    void act(async () => {
      if (old === "") { await api.addCollection(draft); onCollections(await api.selectCollection(draft)); }
      else onCollections(await api.renameCollection(old, draft));
      onUsers(await api.users());
    });
  };
  const form = (
    <div className="coll-add">
      <div className="row">
        <input autoFocus type="text" value={draft} aria-label={editing ? `new name for ${editing}` : "new collection name"} aria-invalid={!!draftErr}
          placeholder={editing ? "new name" : "e.g. rf-sintering"} onFocus={(e) => e.target.select()}
          onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") submit(); if (e.key === "Escape") stop(); }} />
        <button type="button" className="primary" disabled={!draft || !!draftErr || busy} onClick={submit}>{editing ? "rename" : "add"}</button>
        <button type="button" className="secondary" onClick={stop}>cancel</button>
      </div>
      {draftErr ? <div className="bad" role="alert">{draftErr}</div>
        : <div className="hint">{editing
          ? `renames the ${editing}/ folder on this Mac${collections.drive_registered ? " and the SSD" : ""} for everyone who uses it; runs keep their data and saved views`
          : `a new, empty collection${me ? ` that ${me.name} records into` : ""}; existing runs stay where they are`}</div>}
    </div>
  );

  return (
    <>
      <div className="hint">
        A collection is a folder of runs{collections.drive_registered ? " (on this Mac and the SSD)" : ""}. One person can record into several, and several people can share one.
        {me ? <> <b>{me.name}</b> is recording into <b>{collections.selected || "—"}</b>.</> : " Pick who's using this from the menu at the top."}
        {locked && " Locked while a recording or armed trigger is active."}
      </div>
      <table className="coll-table">
        <thead><tr><th>collection</th><th>used by</th><th>where</th><th /></tr></thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={4} className="muted">No collections yet.</td></tr>}
          {rows.map((r) => (
            <tr key={r.name} className={r.selected ? "on" : undefined}>
              <td className="nm">{r.name}{r.selected && <span className="tag">recording here</span>}</td>
              <td>{r.users.join(", ") || <span className="muted">—</span>}</td>
              <td>{r.where}</td>
              <td className="acts">
                {!r.selected && <button type="button" className="linkish" disabled={locked || busy} onClick={() => record(r.name)}>record here</button>}
                <button type="button" className="linkish" disabled={locked || busy} onClick={() => { setEditing(r.name); setDraft(r.name); setErr(null); }}>rename…</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {editing === null
        ? <button type="button" className="linkish" disabled={locked} onClick={() => { setEditing(""); setDraft(""); setErr(null); }}>+ new collection</button>
        : form}
      {err && <div className="errbox">{err}</div>}
      <h3 style={{ marginTop: 16 }}>Sort loose runs into a collection</h3>
      <CollectionsMigrationPanel defaultTarget={collections.selected || ""} />
    </>
  );
}
