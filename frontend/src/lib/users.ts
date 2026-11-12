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
