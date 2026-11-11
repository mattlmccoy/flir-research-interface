// Collections in the browser: name rules, picker entries and the Record gate. Mirrors the
// operator's rules (backend collections.py collection_name_error, api/app.py
// _recording_collection) so the UI explains a refusal before the operator answers 400/409.

import type { CollectionsDoc } from "./api.ts";

const NAME_RE = /^[a-z0-9_-]{1,40}$/;
const RUN_LIKE_RE = /^\d{8}_\d{6}(_|$)/;

/** The operator's 409 while a recording or armed trigger is active (collections_routes.py). */
export const PICKER_LOCK_MESSAGE = "the collection can't change while a recording or armed trigger is active";
export const PICK_BEFORE_RECORDING = "pick a collection before recording";

/** null when `name` is a valid collection name, otherwise the operator's reason (same text). */
export function collectionNameError(name: string): string | null {
  if (name.startsWith(".")) return "A collection name cannot start with a dot.";
  if (RUN_LIKE_RE.test(name)) return "A collection name cannot look like a run folder (YYYYMMDD_HHMMSS...).";
  if (!NAME_RE.test(name)) return "Use 1-40 characters: lowercase letters, digits, '-' and '_'.";
  return null;
}

export interface PickerEntry { value: string; label: string; disabled: boolean; note: string | null; }

function collectionNote(c: CollectionsDoc["collections"][number]): string | null {
  if (c.offline) return "offline";
  if (c.local && c.drive) return null;
  return c.drive ? "on drive only" : "on this Mac only";
}

/** Collections A-Z, then Unsorted (when it holds runs or is selected), then the unexpected folders
 *  (disabled: shown so nothing on disk is hidden, never selectable). */
export function pickerEntries(doc: CollectionsDoc): PickerEntry[] {
  const cols = [...doc.collections].sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  const out: PickerEntry[] = cols.map((c) => ({ value: c.name, label: c.name, disabled: false, note: collectionNote(c) }));
  const n = doc.unsorted.local + doc.unsorted.drive;
  if (n > 0 || doc.selected === "") out.push({ value: "", label: `Unsorted (${n})`, disabled: false, note: null });
  for (const u of doc.unexpected) {
    out.push({ value: `${u.library}:${u.name}`, label: u.name, disabled: true, note: "not a collection or run; left untouched" });
  }
  return out;
}

/** Record and Arm need a collection. A collection only on the unplugged drive is fine: the
 *  operator records it to the Mac and creates the folder (ruling R1). */
export function canRecord(doc: CollectionsDoc): { ok: boolean; reason: string | null } {
  return doc.selected ? { ok: true, reason: null } : { ok: false, reason: PICK_BEFORE_RECORDING };
}

/** What the top bar and "Recording to:" show for a selection. */
export function collectionLabel(selected: string | null): string {
  if (selected === null) return "no collection";
  return selected === "" ? "Unsorted" : selected;
}

/** The operator refuses a selection change while a recording or armed trigger is active. */
export function pickerLocked(rec: { state: string } | null): boolean {
  return !!rec && (rec.state === "recording" || rec.state === "armed");
}
