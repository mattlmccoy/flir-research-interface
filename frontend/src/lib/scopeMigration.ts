// One-time re-keying of per-run browser state from `exp.<name>` to `exp.<collection>/<name>` once
// runs live in collections. The key formats come from their producers: roiKeyFor (roi.ts),
// maskKeyFor (mask.ts) and offsetsKey (labelDrag.ts, also with the `.mask` scope PlaybackPage uses).
// smartView keys live inside the layout, so they are returned as `rename` for the layout reducer.

import { roiKeyFor } from "./roi.ts";
import { maskKeyFor } from "./mask.ts";
import { offsetsKey } from "./labelDrag.ts";
import { runKey } from "./runKey.ts";

export interface RunLocation { collection: string | null; name: string; }
export interface ScopeMigration {
  /** Old storage keys whose value now lives under the new key. */
  moved: string[];
  /** Run names found in more than one place: their state is left alone. */
  ambiguous: string[];
  /** `exp.<name>` → `exp.<collection>/<name>` for each run that lives in exactly one collection. */
  rename: Record<string, string>;
}

const FAMILIES: ((scope: string) => string)[] = [
  roiKeyFor,
  maskKeyFor,
  (scope) => offsetsKey(scope),
  (scope) => offsetsKey(`${scope}.mask`),
];

/** Moves each family's `exp.<name>` value to `exp.<c>/<name>` when the run's only location is
 *  collection `c`. An existing new key is never overwritten (the old key then stays). Top-level
 *  runs keep their key. Idempotent. */
export function migrateRunScopes(storage: Storage, locations: RunLocation[]): ScopeMigration {
  const where = new Map<string, Set<string | null>>();
  for (const l of locations) {
    const s = where.get(l.name) ?? new Set<string | null>();
    s.add(l.collection || null);
    where.set(l.name, s);
  }
  const out: ScopeMigration = { moved: [], ambiguous: [], rename: {} };
  for (const [name, colls] of where) {
    if (colls.size > 1) { out.ambiguous.push(name); continue; }
    const [coll] = colls;
    if (!coll) continue;
    const from = `exp.${name}`;
    const to = `exp.${runKey(coll, name)}`;
    out.rename[from] = to;
    for (const key of FAMILIES) {
      const oldKey = key(from);
      const newKey = key(to);
      const value = storage.getItem(oldKey);
      if (value === null || storage.getItem(newKey) !== null) continue;
      storage.setItem(newKey, value);
      storage.removeItem(oldKey);
      out.moved.push(oldKey);
    }
  }
  return out;
}
