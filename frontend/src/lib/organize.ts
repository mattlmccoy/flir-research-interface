// Pure logic for organizing experiments: tag normalization + autocomplete, star/tag filtering,
// sorting, and the multi-select reducer. No React, so it is unit-tested directly. Mirrors the
// backend's flir_research_interface/labels.py normalization so the UI never sends junk.
const MAX_TAG = 40;

export function normalizeTag(s: string): string {
  return s.split(/\s+/).filter(Boolean).join(" ").slice(0, MAX_TAG);
}

export function mergeTags(existing: string[], add: string[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of [...existing, ...add]) {
    const t = normalizeTag(raw);
    if (!t) continue;
    const k = t.toLowerCase();
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(t);
  }
  return out;
}

type Tagged = { tags?: string[] };
export function tagUniverse(items: readonly Tagged[]): { tag: string; count: number }[] {
  const counts = new Map<string, { tag: string; count: number }>();
  for (const it of items) {
    for (const raw of it.tags ?? []) {
      const t = normalizeTag(raw);
      if (!t) continue;
      const k = t.toLowerCase();
      const cur = counts.get(k);
      if (cur) cur.count += 1;
      else counts.set(k, { tag: t, count: 1 });
    }
  }
  return [...counts.values()].sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag));
}

export function suggestTags(all: string[], query: string, exclude: string[]): string[] {
  const q = query.trim().toLowerCase();
  const ex = new Set(exclude.map((t) => t.toLowerCase()));
  return tagUniverse(all.map((t) => ({ tags: [t] })))
    .map((f) => f.tag)
    .filter((t) => !ex.has(t.toLowerCase()) && (!q || t.toLowerCase().includes(q)))
    .slice(0, 8);
}

type Exp = {
  name: string; starred?: boolean; tags?: string[];
  started_utc?: string | null; duration_s?: number;
  title?: string | null; notes?: string | null;
};

/** What a run is called on screen: its display title when set, else its folder name. */
export const displayName = (e: { name: string; title?: string | null }): string =>
  (e.title ?? "").trim() || e.name;

export function filterExperiments<T extends Exp>(
  items: T[], f: { query: string; starredOnly: boolean; tags: string[] },
): T[] {
  const q = f.query.trim().toLowerCase();
  const need = f.tags.map((t) => t.toLowerCase());
  return items.filter((e) => {
    if (f.starredOnly && !e.starred) return false;
    const tags = (e.tags ?? []).map((t) => t.toLowerCase());
    if (need.some((t) => !tags.includes(t))) return false;
    if (!q) return true;
    const text = [e.name, e.title ?? "", e.notes ?? ""].join("\n").toLowerCase();
    return text.includes(q) || tags.some((t) => t.includes(q));
  });
}

/** New display titles for a bulk rename. Runs are taken in recording order — the folder name's
 *  YYYYMMDD_HHMMSS prefix (every recorded run has one), else started_utc, else the name; never a mix
 *  of the two clocks — so "1, 2, 3" follows the experiment sequence, not click order. With
 *  `numbered`, titles are "<base> NN" zero-padded to the count's width (so they also sort by
 *  name); otherwise every run gets `base`. A blank base yields "" for each run, which clears it. */
export function bulkTitles(
  items: { name: string; started_utc?: string | null }[], base: string, numbered: boolean,
): { name: string; title: string }[] {
  const b = base.trim().replace(/\s+/g, " ");
  const when = (e: { name: string; started_utc?: string | null }) =>
    /^\d{8}_\d{6}/.exec(e.name)?.[0] ?? e.started_utc ?? e.name;
  const ordered = [...items].sort((a, c) => when(a).localeCompare(when(c)) || a.name.localeCompare(c.name));
  const width = String(ordered.length).length;
  return ordered.map((e, i) => ({
    name: e.name,
    title: !b ? "" : numbered ? `${b} ${String(i + 1).padStart(width, "0")}` : b,
  }));
}

export type Sort = "newest" | "name" | "duration" | "starred";
export function sortExperiments<T extends Exp>(items: T[], sort: Sort): T[] {
  const newest = (a: T, b: T) =>
    (b.started_utc ?? "").localeCompare(a.started_utc ?? "") || b.name.localeCompare(a.name);
  return [...items].sort((a, b) => {
    if (sort === "name") return displayName(a).localeCompare(displayName(b));
    if (sort === "duration") return (b.duration_s ?? 0) - (a.duration_s ?? 0);
    if (sort === "starred") return Number(!!b.starred) - Number(!!a.starred) || newest(a, b);
    return newest(a, b);
  });
}

export type SelectionState = { anchor: string | null; selected: Set<string> };
export type SelectionAction =
  | { type: "toggle"; name: string }
  | { type: "range"; name: string; order: string[] }
  | { type: "selectAll"; names: string[] }
  | { type: "clear" };

export function selectionReducer(s: SelectionState, a: SelectionAction): SelectionState {
  if (a.type === "clear") return { anchor: null, selected: new Set() };
  if (a.type === "selectAll") return { anchor: s.anchor, selected: new Set(a.names) };
  const selected = new Set(s.selected);
  if (a.type === "toggle") {
    if (selected.has(a.name)) selected.delete(a.name);
    else selected.add(a.name);
    return { anchor: a.name, selected };
  }
  // range: select everything between the anchor and name in the given order
  const i = a.order.indexOf(s.anchor ?? a.name);
  const j = a.order.indexOf(a.name);
  if (i >= 0 && j >= 0) {
    for (const n of a.order.slice(Math.min(i, j), Math.max(i, j) + 1)) selected.add(n);
  } else {
    selected.add(a.name);
  }
  return { anchor: a.name, selected };
}
