import { test } from "node:test";
import assert from "node:assert/strict";
import { createRunScopeMigrator, migrateRunScopes, openRun, type RunLocation } from "./scopeMigration.ts";
import { saveRois, loadRois } from "./roi.ts";
import { EMPTY_MASKS, saveMasks } from "./mask.ts";
import { offsetsKey, saveOffsets } from "./labelDrag.ts";

// The stored keys are written by the real producers (saveRois, saveMasks, saveOffsets/offsetsKey,
// with the scopes PlaybackPage passes: `exp.<name>` and `exp.<name>.mask`). Browser storage on the
// lab operator is off limits, so the values themselves are hand-made shapes, not captured ones.

function memStorage(): Storage {
  const m = new Map<string, string>();
  return {
    get length() { return m.size; },
    clear: () => m.clear(), key: (i) => [...m.keys()][i] ?? null,
    getItem: (k) => m.get(k) ?? null, setItem: (k, v) => void m.set(k, String(v)), removeItem: (k) => void m.delete(k),
  } as Storage;
}

const RUN = "20261102_165506_Run";

/** Writes all four key families for `exp.<name>`; returns the keys the producers built. */
function seed(st: Storage, name: string): string[] {
  const scope = `exp.${name}`;
  saveRois(st, { rois: [{ id: 1, kind: "spot", x: 1, y: 1, box: 3 }], selected: null, selectedIds: [], nextId: 2 }, scope);
  saveMasks(st, { ...EMPTY_MASKS, enabled: false }, scope);
  saveOffsets(st, scope, { 1: { dx: 4, dy: 5 } });
  saveOffsets(st, `${scope}.mask`, { 2: { dx: 6, dy: 7 } });
  return [`fri.rois.${scope}`, `flir.masks.v1.${scope}`, offsetsKey(scope), offsetsKey(`${scope}.mask`)];
}

function snapshot(st: Storage): Record<string, string> {
  const out: Record<string, string> = {};
  for (let i = 0; i < st.length; i++) { const k = st.key(i)!; out[k] = st.getItem(k)!; }
  return out;
}

test("migrates every key family", () => {
  const st = memStorage();
  const oldKeys = seed(st, RUN);
  const before = snapshot(st);
  const r = migrateRunScopes(st, [{ collection: "mattmccoy", name: RUN }]);
  const newScope = `exp.mattmccoy/${RUN}`;
  const newKeys = [`fri.rois.${newScope}`, `flir.masks.v1.${newScope}`, offsetsKey(newScope), offsetsKey(`${newScope}.mask`)];
  oldKeys.forEach((k, i) => {
    assert.equal(st.getItem(k), null, `old key ${k} removed`);
    assert.equal(st.getItem(newKeys[i]), before[k], `value now under ${newKeys[i]}`);
  });
  assert.deepEqual([...r.moved].sort(), [...oldKeys].sort());
  assert.deepEqual(r.ambiguous, []);
  assert.deepEqual(r.rename, { [`exp.${RUN}`]: newScope });
  assert.equal(loadRois(st, newScope).rois.length, 1, "the real loader reads the moved ROIs");
});

test("never overwrites an existing new key", () => {
  const st = memStorage();
  seed(st, RUN);
  const newRois = `fri.rois.exp.mattmccoy/${RUN}`;
  st.setItem(newRois, "NEWER");
  const oldRois = `fri.rois.exp.${RUN}`;
  const oldValue = st.getItem(oldRois);
  const r = migrateRunScopes(st, [{ collection: "mattmccoy", name: RUN }]);
  assert.equal(st.getItem(newRois), "NEWER", "the existing new key is untouched");
  assert.equal(st.getItem(oldRois), oldValue, "the old key is kept");
  assert.ok(!r.moved.includes(oldRois));
  assert.equal(r.moved.length, 3, "the other families still move");
});

test("leaves ambiguous names", () => {
  const st = memStorage();
  seed(st, RUN);
  const before = snapshot(st);
  const r = migrateRunScopes(st, [{ collection: "mattmccoy", name: RUN }, { collection: "rf-sintering", name: RUN }]);
  assert.deepEqual(r.ambiguous, [RUN]);
  assert.deepEqual(r.moved, []);
  assert.deepEqual(r.rename, {});
  assert.deepEqual(snapshot(st), before, "nothing moves");
});

test("top-level runs keep their key", () => {
  const st = memStorage();
  seed(st, RUN);
  const before = snapshot(st);
  // The same location reported twice (local + offline index) is one location, not an ambiguity.
  const r = migrateRunScopes(st, [{ collection: null, name: RUN }, { collection: null, name: RUN }]);
  assert.deepEqual(r, { moved: [], ambiguous: [], rename: {} });
  assert.deepEqual(snapshot(st), before);
});

test("is idempotent", () => {
  const st = memStorage();
  seed(st, RUN);
  const locs = [{ collection: "mattmccoy", name: RUN }];
  migrateRunScopes(st, locs);
  const after = snapshot(st);
  const r = migrateRunScopes(st, locs);
  assert.deepEqual(r.moved, []);
  assert.deepEqual(snapshot(st), after);
});

test("other scopes and other runs are untouched", () => {
  const st = memStorage();
  seed(st, "20261103_000000_other");
  saveRois(st, { rois: [], selected: null, selectedIds: [], nextId: 1 }, "live");
  const before = snapshot(st);
  const r = migrateRunScopes(st, [{ collection: "mattmccoy", name: RUN }]);
  assert.deepEqual(r.moved, []);
  assert.deepEqual(snapshot(st), before);
});

// -- the migrator: when the re-key runs relative to opening a run (fix round 1) --

function deferred<T>() {
  let resolve!: (v: T) => void, reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

test("migrator: concurrent ensure() calls share one fetch", async () => {
  const st = memStorage();
  seed(st, RUN);
  const d = deferred<RunLocation[]>();
  let fetches = 0;
  const renames: Record<string, string>[] = [];
  const m = createRunScopeMigrator(() => { fetches++; return d.promise; }, st, (r) => renames.push(r));
  const a = m.ensure(), b = m.ensure();
  d.resolve([{ collection: "mattmccoy", name: RUN }]);
  await Promise.all([a, b]);
  assert.equal(fetches, 1);
  assert.deepEqual(renames, [{ [`exp.${RUN}`]: `exp.mattmccoy/${RUN}` }]);
  assert.equal(st.getItem(`fri.rois.exp.${RUN}`), null, "migrated");
});

test("migrator: a rejected fetch clears the memo, so the next ensure() retries and migrates", async () => {
  const st = memStorage();
  seed(st, RUN);
  let calls = 0;
  const m = createRunScopeMigrator(async () => {
    calls++;
    if (calls === 1) throw new Error("operator down");
    return [{ collection: "mattmccoy", name: RUN }];
  }, st, () => undefined);
  await assert.rejects(m.ensure(), /operator down/);
  assert.notEqual(st.getItem(`fri.rois.exp.${RUN}`), null, "nothing moved on failure");
  await m.ensure();
  assert.equal(calls, 2);
  assert.equal(st.getItem(`fri.rois.exp.${RUN}`), null);
  assert.notEqual(st.getItem(`fri.rois.exp.mattmccoy/${RUN}`), null);
});

test("openRun: the migration completes before the run is opened; a failure does not open it", async () => {
  const st = memStorage();
  seed(st, RUN);
  const m = createRunScopeMigrator(async () => [{ collection: "mattmccoy", name: RUN }], st, () => undefined);
  let seenAtOpen: string | null | undefined;
  await openRun(`mattmccoy/${RUN}`, m, () => { seenAtOpen = st.getItem(`fri.rois.exp.mattmccoy/${RUN}`); });
  assert.ok(seenAtOpen, "the new scope already holds the old ROIs when the run opens");

  const failing = createRunScopeMigrator(async () => { throw new Error("operator down"); }, memStorage(), () => undefined);
  let opened = false;
  await assert.rejects(openRun("mattmccoy/x", failing, () => { opened = true; }), /operator down/);
  assert.equal(opened, false);
});

test("migrator: a backend move after the first ensure() is re-keyed by the next one", async () => {
  const st = memStorage();
  seed(st, RUN);
  let locs: RunLocation[] = [{ collection: null, name: RUN }];
  const renames: Record<string, string>[] = [];
  const m = createRunScopeMigrator(async () => locs, st, (r) => renames.push(r));
  await m.ensure();
  assert.notEqual(st.getItem(`fri.rois.exp.${RUN}`), null, "top level: unchanged");
  assert.deepEqual(renames, [], "no rename for a top-level run");
  locs = [{ collection: "mattmccoy", name: RUN }];  // the operator moved it into mattmccoy/
  await m.ensure();
  assert.equal(st.getItem(`fri.rois.exp.${RUN}`), null);
  assert.notEqual(st.getItem(`fri.rois.exp.mattmccoy/${RUN}`), null);
  assert.deepEqual(renames, [{ [`exp.${RUN}`]: `exp.mattmccoy/${RUN}` }]);
});
