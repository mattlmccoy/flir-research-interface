import { test } from "node:test";
import assert from "node:assert/strict";
import type { CollectionsDoc, MigrationPlanDoc } from "./api.ts";
import { confirmPayload, confirmText, migrationSummary, moveTargets } from "./migrationView.ts";

// hand-made shape mirroring the operator's GET /api/collections/migration
// (api/collections_routes.py _plan_doc); the run names follow the real YYYYMMDD_HHMMSS_ pattern
function plan(n: number, over: Partial<MigrationPlanDoc> = {}): MigrationPlanDoc {
  const moves = Array.from({ length: n }, (_, i) => {
    const name = `20260902_${String(150000 + i).padStart(6, "0")}_run`;
    return { name, src: `/r/${name}`, dst: `/r/mattmccoy/${name}` };
  });
  return {
    volume: "local", base: "/r", target: "mattmccoy", moves, conflicts: [],
    appledouble: 0, unexpected: [], already_in_target: 0, busy: [], ...over,
  };
}

test("summary counts", () => {
  const p = plan(92, { appledouble: 90, conflicts: [{ name: "x", reason: "mattmccoy/ already has x" }] });
  assert.equal(migrationSummary(p), "92 runs → mattmccoy/ · 90 macOS ._ files removed · 1 conflict");
  assert.equal(migrationSummary(plan(1)), "1 run → mattmccoy/ · 0 macOS ._ files removed · 0 conflicts");
});

test("confirm text lists every move", () => {
  const p = plan(3);
  const text = confirmText(p);
  for (const m of p.moves) assert.ok(text.includes(`${m.src} → ${m.dst}`), m.name);
  assert.ok(text.startsWith("Move 3 runs into mattmccoy?"));
});

test("confirm payload is exactly the planned names", () => {
  const p = plan(5, { conflicts: [{ name: "c", reason: "r" }], unexpected: ["Old Stuff"] });
  assert.deepEqual(confirmPayload(p), { volume: "local", target: "mattmccoy", confirm: p.moves.map((m) => m.name) });
});

// hand-made shape mirroring GET /api/collections (_doc)
const DOC: CollectionsDoc = {
  selected: "mattmccoy",
  collections: [
    { name: "mattmccoy", local: true, drive: false, offline: false },
    { name: "demo", local: true, drive: true, offline: false },
    { name: "rf-sintering", local: false, drive: true, offline: true },
  ],
  unsorted: { local: 0, drive: 0 }, unexpected: [], drive_connected: false, drive_registered: true,
};

test("move targets exclude current and offline-only", () => {
  assert.deepEqual(moveTargets(DOC, "mattmccoy"), ["", "demo"]);
  assert.deepEqual(moveTargets(DOC, null), ["demo", "mattmccoy"]);
  assert.deepEqual(moveTargets(null, null), []);
});
