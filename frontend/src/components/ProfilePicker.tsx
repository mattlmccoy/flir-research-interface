import { useEffect, useState } from "react";
import { api, type CollectionsDoc, type UserInfo, type UsersDoc } from "../lib/api.ts";
import { slugFor, USER_LOCK_MESSAGE } from "../lib/users.ts";
import { Avatar, usePhotoPicker } from "./Avatar.tsx";

/** The "who's at the bench?" screen shown when the app opens (unless this browser opted out) and
 *  from the user menu. Picking a person switches the operator to them and their last collection;
 *  each tile also takes a profile photo. While recording, the current person can only continue. */
export function ProfilePicker({ users, usersErr, locked, showAtStartup, onShowAtStartup, onUsers, onCollections, onClose }: {
  users: UsersDoc | null; usersErr: string | null; locked: boolean;
  showAtStartup: boolean; onShowAtStartup: (show: boolean) => void;
  onUsers: (d: UsersDoc) => void; onCollections: (d: CollectionsDoc) => void; onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !adding) onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [adding, onClose]);

  async function act(fn: () => Promise<void>, close = true) {
    setBusy(true); setErr(null);
    try { await fn(); if (close) onClose(); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }
  const pick = (u: UserInfo) => {
    if (u.id === users?.current) { onClose(); return; }
    void act(async () => { onUsers(await api.selectUser(u.id)); onCollections(await api.collections()); });
  };
  const photo = usePhotoPicker((url, id) => void act(async () => onUsers(await api.setAvatar(id, url)), false), setErr);
  const slug = slugFor(draft);
  const draftErr = draft.trim() === "" ? null : !slug ? "the name needs at least one letter or digit"
    : users?.users.some((u) => u.id === slug) ? `${slug} is already here` : null;
  const add = () => {
    if (!slug || draftErr || busy) return;
    void act(async () => {
      const d = await api.addUser(draft);
      const added = d.users.find((u) => u.id === slug);
      onUsers(added ? await api.selectUser(added.id) : d);
      onCollections(await api.collections());
    });
  };

  return (
    <div className="pp-scrim" role="dialog" aria-modal="true" aria-labelledby="pp-title">
      {photo.el}
      <div className="pp-card">
        <div className="pp-eyebrow">FLIR research interface</div>
        <h1 id="pp-title">Who's at the bench?</h1>
        <p className="pp-sub">
          {locked ? USER_LOCK_MESSAGE + "." : "Your recordings go to your collections, with your project profile."}
        </p>
        {!users && <p className="pp-sub bad">{usersErr ? `users unavailable: ${usersErr}` : "loading…"}</p>}
        <div className="pp-grid">
          {users?.users.map((u) => {
            const me = u.id === users.current;
            return (
              <div key={u.id} className={`pp-tile${me ? " me" : ""}`}>
                <button type="button" className="pp-pick" disabled={busy || (locked && !me)}
                  title={locked && !me ? USER_LOCK_MESSAGE : `continue as ${u.name}`} onClick={() => pick(u)}>
                  <Avatar user={u} size={88} className="pp-av" />
                  <span className="pp-nm">{u.name}</span>
                  <span className="pp-meta">{me ? "last here" : u.last_collection ?? ""}</span>
                </button>
                <button type="button" className="pp-cam" disabled={busy} aria-label={`${u.avatar ? "change" : "add"} ${u.name}'s photo`}
                  title={u.avatar ? "change photo" : "add a photo"} onClick={() => photo.open(u.id)}>
                  <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden><path fill="currentColor" d="M9 4 7.2 6H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-3.2L15 4H9Zm3 4.5a4.5 4.5 0 1 1 0 9 4.5 4.5 0 0 1 0-9Zm0 2a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5Z" /></svg>
                </button>
                {u.avatar && (
                  <button type="button" className="pp-rm" disabled={busy} title="remove photo" aria-label={`remove ${u.name}'s photo`}
                    onClick={() => void act(async () => onUsers(await api.clearAvatar(u.id)), false)}>×</button>
                )}
              </div>
            );
          })}
          {users && !locked && (
            <div className="pp-tile add">
              {!adding
                ? <button type="button" className="pp-pick" onClick={() => setAdding(true)}>
                  <span className="avatar pp-av plus" aria-hidden>+</span>
                  <span className="pp-nm">add person</span>
                  <span className="pp-meta">&nbsp;</span>
                </button>
                : <div className="pp-addform">
                  <input autoFocus type="text" value={draft} placeholder="full name" aria-label="new person's name" aria-invalid={!!draftErr}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") add(); if (e.key === "Escape") { setAdding(false); setDraft(""); } }} />
                  <button type="button" className="primary" disabled={!slug || !!draftErr || busy} onClick={add}>add</button>
                  <div className={draftErr ? "bad" : "pp-meta"}>{draftErr ?? (slug ? `records into ${slug}/` : "e.g. Ana Ruiz")}</div>
                </div>}
            </div>
          )}
        </div>
        {err && <div className="pp-err" role="alert">{err}</div>}
        <div className="pp-foot">
          <label className="pp-check">
            <input type="checkbox" checked={showAtStartup} onChange={(e) => onShowAtStartup(e.target.checked)} />
            show this when the app opens
          </label>
          <button type="button" className="secondary" onClick={onClose}>
            {users?.current ? "skip" : "not now"} →
          </button>
        </div>
      </div>
    </div>
  );
}
