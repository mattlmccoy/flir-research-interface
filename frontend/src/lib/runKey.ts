// A run's address in the browser: "<collection>/<name>", or the bare name for a run at the top
// level of a root. Same shape as the operator's RunRef.key (backend collections.py). Run and
// collection names never contain "/", so the first "/" splits them.

export type RunKey = string;

export function runKey(collection: string | null | undefined, name: string): RunKey {
  return collection ? `${collection}/${name}` : name;
}

export function parseRunKey(k: RunKey): { collection: string | null; name: string } {
  const i = k.indexOf("/");
  return i < 0 ? { collection: null, name: k } : { collection: k.slice(0, i), name: k.slice(i + 1) };
}

/** The run folder name (what is shown and used in file names). */
export function runName(k: RunKey): string {
  return parseRunKey(k).name;
}

export function keyOf(e: { collection?: string | null; name: string }): RunKey {
  return runKey(e.collection, e.name);
}

/** `/api/experiments/<name><suffix>` plus `collection=` (empty for the top level) after any query
 *  already in `suffix`, so the operator never falls back to its legacy unique-name lookup. */
export function runPath(k: RunKey, suffix = ""): string {
  const { collection, name } = parseRunKey(k);
  const sep = suffix.includes("?") ? "&" : "?";
  return `/api/experiments/${encodeURIComponent(name)}${suffix}${sep}collection=${encodeURIComponent(collection ?? "")}`;
}
