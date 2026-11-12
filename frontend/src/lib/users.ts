// User profiles in the browser: who is at the bench and the collections they use. Mirrors the
// operator (backend users.py); a user points at shared, flat collections and never owns folders.

import type { CollectionsDoc, UserInfo, UsersDoc } from "./api.ts";

/** The operator's 409 while a recording or armed trigger is active (users_routes.py). */
export const USER_LOCK_MESSAGE = "the user can't change while a recording or armed trigger is active";

/** The id a display name gets (backend users.slug_for): ASCII-folded, lowercase, spaces dropped,
 *  only [a-z0-9_-] kept, at most 40 characters. Shown as a preview before adding someone. */
export function slugFor(name: string): string {
  const folded = name.normalize("NFKD").replace(/[^\x00-\x7f]/g, "");
  return folded.toLowerCase().replace(/[^a-z0-9_-]/g, "").slice(0, 40);
}

export function currentUser(doc: UsersDoc | null): UserInfo | null {
  if (!doc || !doc.current) return null;
  return doc.users.find((u) => u.id === doc.current) ?? null;
}

/** The top-bar button text: the person's name, a prompt when nobody is chosen, never a silent
 *  "loading…" after a failed fetch. */
export function userChipLabel(doc: UsersDoc | null, err: string | null): string {
  if (doc) return currentUser(doc)?.name ?? "who's using this?";
  return err ? `users unavailable: ${err}` : "loading…";
}

/** The user's collections first (in their order, including ones the doc can't see right now, e.g.
 *  only on the unplugged drive), then every other collection A-Z. */
export function userMenuCollections(user: UserInfo, doc: CollectionsDoc): { mine: string[]; others: string[] } {
  const mine = [...user.collections];
  const others = doc.collections.map((c) => c.name).filter((n) => !mine.includes(n)).sort();
  return { mine, others };
}

export interface CollectionRow { name: string; users: string[]; where: string; selected: boolean; }

/** The Setup page's collection table: every collection A-Z, the people whose list has it, where
 *  its folder is (this Mac, the SSD, or the unplugged SSD's last-seen index) and the selection. */
export function collectionRows(doc: CollectionsDoc, users: UsersDoc | null): CollectionRow[] {
  return [...doc.collections].sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0)).map((c) => {
    const ssd = c.offline ? "SSD (unplugged)" : "SSD";
    const where = c.local && c.drive ? `Mac + ${ssd}` : c.drive ? ssd : "Mac";
    const who = (users?.users ?? []).filter((u) => u.collections.includes(c.name)).map((u) => u.name);
    return { name: c.name, users: who, where, selected: c.name === doc.selected };
  });
}

/** Avatar fallback letters: first letter of the first and last word ("Matt McCoy" -> "MM"). */
export function initials(name: string): string {
  const w = name.trim().split(/\s+/).filter(Boolean);
  if (w.length === 0) return "?";
  return (w[0][0] + (w.length > 1 ? w[w.length - 1][0] : "")).toUpperCase();
}

/** The centred square of a w x h photo and the output side (``target``, never upscaled). Any size
 *  photo is accepted: the browser crops and shrinks it before upload. */
export function squareCrop(w: number, h: number, target: number): { sx: number; sy: number; side: number; out: number } {
  const side = Math.min(w, h);
  return { sx: Math.floor((w - side) / 2), sy: Math.floor((h - side) / 2), side, out: Math.min(side, target) };
}

type KV = Pick<Storage, "getItem" | "setItem" | "removeItem">;
const PICKER_KEY = "fri.profilePicker.skip";

/** Whether this browser shows the "who's using this?" screen when the app opens. */
export function pickerAtStartup(store: KV | null): boolean {
  try { return store?.getItem(PICKER_KEY) !== "1"; } catch { return true; }
}

export function setPickerAtStartup(store: KV | null, show: boolean): void {
  try { if (show) store?.removeItem(PICKER_KEY); else store?.setItem(PICKER_KEY, "1"); } catch { /* storage blocked: stays on */ }
}
