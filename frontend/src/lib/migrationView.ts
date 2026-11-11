// The collections migration panel and the "move to collection…" action: pure view logic over the
// operator's migration plan (backend api/collections_routes.py _plan_doc) and collections doc.

import type { CollectionsDoc, MigrationPlanDoc } from "./api.ts";

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** One line: "92 runs → mattmccoy/ · 90 macOS ._ files removed · 0 conflicts". */
export function migrationSummary(plan: MigrationPlanDoc): string {
  return `${plural(plan.moves.length, "run")} → ${plan.target}/ · ${plan.appledouble} macOS ._ files removed · ${plural(plan.conflicts.length, "conflict")}`;
}

/** The confirm dialog: every `src → dst`, so nothing moves that was not shown. */
export function confirmText(plan: MigrationPlanDoc): string {
  const lines = plan.moves.map((m) => `${m.src} → ${m.dst}`);
  return `Move ${plural(plan.moves.length, "run")} into ${plan.target}?\n\n${lines.join("\n")}\n\nSame-volume renames only; nothing is copied or overwritten.`;
}

/** The POST body: exactly the planned names (never conflicts or unexpected folders). */
export function confirmPayload(plan: MigrationPlanDoc): { volume: "local" | "drive"; target: string; confirm: string[] } {
  return { volume: plan.volume, target: plan.target, confirm: plan.moves.map((m) => m.name) };
}

/** Where a run in `current` (null = Unsorted) can move: "" (Unsorted) unless it is there, then
 *  every collection but its own. Offline-only collections are left out: their folder is on an
 *  unplugged drive, and a move is a same-volume rename. */
export function moveTargets(doc: CollectionsDoc | null, current: string | null): string[] {
  if (!doc) return [];
  const names = doc.collections
    .filter((c) => c.name !== current && !(c.offline && !c.local))
    .map((c) => c.name)
    .sort();
  return current === null ? names : ["", ...names];
}
