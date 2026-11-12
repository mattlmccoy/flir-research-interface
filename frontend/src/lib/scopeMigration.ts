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
export interface CollectionRename { from: string; to: string; }

/** Where collection `name` ended up after every later rename in `renames` (oldest first). */
function finalName(name: string, renames: readonly CollectionRename[], start: number): string {
  let cur = name;
  for (let i = start; i < renames.length; i++) if (renames[i].from === cur) cur = renames[i].to;
  return cur;
}

/** Moves one family's value from `from` to `to` unless `to` already holds state. */
function moveFamilies(storage: Storage, from: string, to: string, moved: string[]): void {
  for (const key of FAMILIES) {
    const oldKey = key(from);
    const newKey = key(to);
    const value = storage.getItem(oldKey);
    if (value === null || storage.getItem(newKey) !== null) continue;
    storage.setItem(newKey, value);
    storage.removeItem(oldKey);
    moved.push(oldKey);
  }
}

/** `renames`: the operator's collection-rename log (GET /api/collections `renames`), oldest
 *  first; a run's state under `exp.<old>/<name>` moves to its current collection's key. */
export function migrateRunScopes(storage: Storage, locations: RunLocation[], renames: readonly CollectionRename[] = []): ScopeMigration {
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
    moveFamilies(storage, from, to, out.moved);
    renames.forEach((r, i) => {
      if (finalName(r.to, renames, i + 1) !== coll) return;
      const old = `exp.${runKey(r.from, name)}`;
      out.rename[old] = to;
      moveFamilies(storage, old, to, out.moved);
    });
  }
  return out;
}

export interface RunScopeMigrator {
  /** Fetches the run locations and re-keys (migrateRunScopes). Concurrent calls share one fetch;
   *  each later call runs again (idempotent), so runs moved mid-session are caught. Rejects when
   *  the fetch fails, and the next call retries. */
  ensure(): Promise<void>;
}

export function createRunScopeMigrator(
  fetchLocations: () => Promise<RunLocation[]>,
  storage: Storage,
  onRename: (rename: Record<string, string>) => void,
  onAmbiguous: (names: string[]) => void = () => undefined,
  fetchRenames: () => Promise<readonly CollectionRename[]> = () => Promise.resolve([]),
): RunScopeMigrator {
  let inFlight: Promise<void> | null = null;
  const run = async (): Promise<void> => {
    const [locations, renames] = await Promise.all([fetchLocations(), fetchRenames()]);
    const r = migrateRunScopes(storage, locations, renames);
    if (Object.keys(r.rename).length) onRename(r.rename);
    if (r.ambiguous.length) onAmbiguous(r.ambiguous);
  };
  return {
    ensure() {
      inFlight ??= run().finally(() => { inFlight = null; });
      return inFlight;
    },
  };
}

/** Opens a run only after its browser state is re-keyed, so the new scope is never seeded (and
 *  saved) ahead of the old state moving into it. A failed migration rejects and opens nothing. */
export async function openRun(key: string, migrator: RunScopeMigrator, setOpen: (key: string) => void): Promise<void> {
  await migrator.ensure();
  setOpen(key);
}
