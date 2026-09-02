import { test } from "node:test";
import assert from "node:assert/strict";
import { EMPTY_ALIGNMENT, alignmentReducer, loadAlignment, saveAlignment } from "./alignment.ts";

const store = () => { const m = new Map<string, string>(); return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => { m.set(k, v); } } as unknown as Storage; };

test("pairs are collected IR-first then visible; incomplete pairs stay pending; removal and clear work", () => {
  let s = alignmentReducer(EMPTY_ALIGNMENT, { type: "pick", side: "ir", p: [0.1, 0.2] });
  assert.deepEqual(s.pending, { ir: [0.1, 0.2] });
  assert.equal(s.pairs.length, 0);
  s = alignmentReducer(s, { type: "pick", side: "visible", p: [0.3, 0.4] });
  assert.equal(s.pending, null);
  assert.deepEqual(s.pairs, [{ ir: [0.1, 0.2], visible: [0.3, 0.4] }]);
  // picking visible first is fine too
  s = alignmentReducer(s, { type: "pick", side: "visible", p: [0.5, 0.5] });
  s = alignmentReducer(s, { type: "pick", side: "ir", p: [0.6, 0.6] });
  assert.equal(s.pairs.length, 2);
  s = alignmentReducer(s, { type: "removePair", index: 0 });
  assert.deepEqual(s.pairs[0].ir, [0.6, 0.6]);
  assert.deepEqual(alignmentReducer(s, { type: "clear" }), EMPTY_ALIGNMENT);
});

test("solve needs 4 pairs, stores H, residual and an rms in IR pixels; unsolved otherwise", () => {
  const pts: [number, number][] = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]];
  let s = EMPTY_ALIGNMENT;
  for (const p of pts.slice(0, 3)) { s = alignmentReducer(s, { type: "pick", side: "ir", p }); s = alignmentReducer(s, { type: "pick", side: "visible", p: [p[0] * 0.8 + 0.1, p[1] * 0.8 + 0.1] }); }
  assert.equal(alignmentReducer(s, { type: "solve", irSize: [640, 480] }).H, null);
  s = alignmentReducer(s, { type: "pick", side: "ir", p: pts[3] }); s = alignmentReducer(s, { type: "pick", side: "visible", p: [pts[3][0] * 0.8 + 0.1, pts[3][1] * 0.8 + 0.1] });
  s = alignmentReducer(s, { type: "solve", irSize: [640, 480] });
  assert.ok(s.H);
  assert.ok(s.rmsPx !== null && s.rmsPx < 1e-6);
  // picking again invalidates the solution
  assert.equal(alignmentReducer(s, { type: "pick", side: "ir", p: [0.5, 0.5] }).H, null);
});

test("saveAlignment / loadAlignment round-trip and reject junk", () => {
  const st = store();
  let s = EMPTY_ALIGNMENT;
  for (let i = 0; i < 4; i++) { const p: [number, number] = [i % 2 ? 0.9 : 0.1, i > 1 ? 0.9 : 0.1]; s = alignmentReducer(s, { type: "pick", side: "ir", p }); s = alignmentReducer(s, { type: "pick", side: "visible", p }); }
  s = alignmentReducer(s, { type: "solve", irSize: [640, 480] });
  s = alignmentReducer(s, { type: "note", note: "sample plane at 0.45 m" });
  saveAlignment(st, s);
  const back = loadAlignment(st);
  assert.deepEqual(back.pairs, s.pairs);
  assert.deepEqual(back.H, s.H);
  assert.equal(back.note, "sample plane at 0.45 m");
  st.setItem("fri.alignment.v1", JSON.stringify({ pairs: "x", H: [[1]] }));
  assert.deepEqual(loadAlignment(st), EMPTY_ALIGNMENT);
  assert.deepEqual(loadAlignment(null), EMPTY_ALIGNMENT);
});
