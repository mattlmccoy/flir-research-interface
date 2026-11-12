import { useEffect, useRef, useState } from "react";
import { api, type CollectionsDoc, type UsersDoc } from "../lib/api.ts";
import { collectionLabel, collectionNameError, renameError } from "../lib/collections.ts";
import { currentUser, slugFor, USER_LOCK_MESSAGE, userChipLabel, userMenuCollections } from "../lib/users.ts";

/** The top-bar "who's using this?" button. Picking a person switches the operator to them and to the
 *  collection they used last; the menu also switches collection and adds people. Shared by every
 *  browser (the operator holds it). Locked while a recording or armed trigger is active. */
export function UserMenu({ users, usersErr, collections, locked, onUsers, onCollections }: {
  users: UsersDoc | null; usersErr: string | null; collections: CollectionsDoc | null; locked: boolean;
  onUsers: (d: UsersDoc) => void; onCollections: (d: CollectionsDoc) => void;
}) {
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");
  const [collMode, setCollMode] = useState<"none" | "new" | "rename">("none");
  const [collDraft, setCollDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);

  const close = () => { setOpen(false); setAdding(false); setDraft(""); setCollMode("none"); setCollDraft(""); setErr(null); };
  useEffect(() => { if (locked) close(); }, [locked]);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) close(); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  async function act(fn: () => Promise<void>, keepOpen = false) {
    setBusy(true); setErr(null);
    try { await fn(); if (!keepOpen) close(); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }
  const switchTo = (id: string) => act(async () => { onUsers(await api.selectUser(id)); onCollections(await api.collections()); });
  const addPerson = (name: string) => act(async () => {
    const d = await api.addUser(name);
    const added = d.users.find((u) => u.id === slugFor(name));
    onUsers(added ? await api.selectUser(added.id) : d);
    onCollections(await api.collections());
  });
  const newCollection = (name: string) => act(async () => {
    await api.addCollection(name);
    onCollections(await api.selectCollection(name));
    onUsers(await api.users());
  });
  const renameSelected = (old: string, next: string) => act(async () => {
    onCollections(await api.renameCollection(old, next));
    onUsers(await api.users());
  });
  const pickCollection = (name: string) => act(async () => { onCollections(await api.selectCollection(name)); onUsers(await api.users()); });

  const me = currentUser(users);
  const unset = !!users && !me;
  const slug = slugFor(draft);
  const draftErr = draft.trim() === "" ? null : !slug ? "the name needs at least one letter or digit"
    : users?.users.some((u) => u.id === slug) ? `${slug} is already a user` : null;
  const groups = me && collections ? userMenuCollections(me, collections) : null;
  const sel = collections?.selected ?? null;
  const collErr = collDraft === "" || !collections ? null
    : collMode === "rename" && sel ? renameError(sel, collDraft, collections)
    : collectionNameError(collDraft) ?? (collections.collections.some((c) => c.name === collDraft) ? `${collDraft} already exists; pick it from the list` : null);
  const submitColl = () => {
    if (!collDraft || collErr || busy) return;
    if (collMode === "rename" && sel) void renameSelected(sel, collDraft);
    else void newCollection(collDraft);
  };

  return (
    <div className="user-menu" ref={box}>
      <button type="button" className={`user-btn${unset ? " unset" : ""}${!users && usersErr ? " error" : ""}`}
        disabled={!users || locked} aria-haspopup="menu" aria-expanded={open}
        title={locked ? USER_LOCK_MESSAGE : "Who's using this? Switch person or collection"}
        onClick={() => (open ? close() : setOpen(true))}>
        <span className="avatar" aria-hidden>{me ? me.name.trim().charAt(0).toUpperCase() : "?"}</span>
        <span className="nm">{userChipLabel(users, usersErr)}</span>
        {me && <span className="sub">→ {collectionLabel(sel)}</span>}
        <span aria-hidden>▾</span>
      </button>
      {open && users && (
        <div className="user-pop" role="menu" aria-label="users">
          <div className="sec-h">who's using this?</div>
          {users.users.length === 0 && <div className="hint">Nobody yet. Add yourself below.</div>}
          {users.users.map((u) => (
            <button key={u.id} type="button" role="menuitemradio" aria-checked={u.id === users.current}
              className={`coll-opt${u.id === users.current ? " on" : ""}`} disabled={busy} onClick={() => switchTo(u.id)}>
              <span className="nm">{u.name}</span><span className="note">{u.profile_name ?? ""}</span>
            </button>
          ))}
          <div className="coll-add">
            {!adding
              ? <button type="button" className="linkish" onClick={() => setAdding(true)}>+ add person</button>
              : <>
                <div className="row">
                  <input autoFocus type="text" value={draft} placeholder="full name, e.g. Ana Ruiz" aria-label="new person's name"
                    aria-invalid={!!draftErr} onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && slug && !draftErr && !busy) void addPerson(draft); }} />
                  <button type="button" className="primary" disabled={!slug || !!draftErr || busy} onClick={() => addPerson(draft)}>add</button>
                </div>
                {draftErr ? <div className="bad" role="alert">{draftErr}</div>
                  : <div className="hint">{slug ? `records into a new collection ${slug}/ with a copy of the lab's project profile` : "their name as the lab knows them"}</div>}
              </>}
          </div>
          {me && groups && (
            <>
              <div className="sec-h">{me.name.split(" ")[0]} records into</div>
              {groups.mine.map((c) => (
                <button key={c} type="button" role="menuitemradio" aria-checked={c === sel}
                  className={`coll-opt${c === sel ? " on" : ""}`} disabled={busy} onClick={() => pickCollection(c)}>
                  <span className="nm">{c}</span>
                </button>
              ))}
              <div className="coll-add">
                {collMode === "none"
                  ? <div className="row">
                    <button type="button" className="linkish" onClick={() => { setCollMode("new"); setCollDraft(""); }}>+ new collection</button>
                    {sel && <button type="button" className="linkish" onClick={() => { setCollMode("rename"); setCollDraft(sel); }}>rename {sel}…</button>}
                  </div>
                  : <>
                    <div className="row">
                      <input autoFocus type="text" value={collDraft} aria-label={collMode === "rename" ? `new name for ${sel}` : "new collection name"}
                        placeholder={collMode === "rename" ? "new name" : "e.g. rf-sintering"} aria-invalid={!!collErr}
                        onFocus={(e) => e.target.select()}
                        onChange={(e) => setCollDraft(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") submitColl(); }} />
                      <button type="button" className="primary" disabled={!collDraft || !!collErr || busy} onClick={submitColl}>{collMode === "rename" ? "rename" : "add"}</button>
                      <button type="button" className="secondary" onClick={() => { setCollMode("none"); setCollDraft(""); }}>cancel</button>
                    </div>
                    {collErr ? <div className="bad" role="alert">{collErr}</div>
                      : <div className="hint">{collMode === "rename"
                        ? `renames the ${sel}/ folder on this Mac${collections?.drive_registered ? " and the SSD" : ""}, for everyone who uses it; runs keep their data and saved views`
                        : "a new, empty collection; existing runs stay where they are"}</div>}
                  </>}
              </div>
              {groups.others.length > 0 && (
                <details className="others">
                  <summary>other collections ({groups.others.length})</summary>
                  {groups.others.map((c) => (
                    <button key={c} type="button" role="menuitemradio" aria-checked={c === sel}
                      className={`coll-opt${c === sel ? " on" : ""}`} disabled={busy}
                      title={`join ${c}: records go there and it's added to ${me.name}'s list`} onClick={() => pickCollection(c)}>
                      <span className="nm">{c}</span><span className="note">shared</span>
                    </button>
                  ))}
                </details>
              )}
            </>
          )}
          {err && <div className="bad" role="alert">{err}</div>}
        </div>
      )}
    </div>
  );
}
