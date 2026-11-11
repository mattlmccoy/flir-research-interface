import { test } from "node:test";
import assert from "node:assert/strict";
import type { CollectionsDoc } from "./api.ts";
import { canRecord, collectionLabel, collectionNameError, pickerEntries, pickerLocked, PICKER_LOCK_MESSAGE } from "./collections.ts";

// The same lists as backend tests/test_collections.py test_valid_collection_names /
// test_rejected_collection_names.
const VALID = ["mattmccoy", "rf-sintering", "a", "x_1", "a".repeat(40)];
const REJECTED = ["", "a".repeat(41), "Matt", "has space", ".hidden", "a/b",
  "20261102_165506_Run", "20261102_165506", "FLIR-recordings", "abc\n", "abc\r\n"];

// hand-made shape mirroring the operator's GET /api/collections (api/collections_routes.py _doc)
function doc(over: Partial<CollectionsDoc> = {}): CollectionsDoc {
  return {
    selected: "mattmccoy",
    collections: [
      { name: "rf-sintering", local: false, drive: true, offline: true },
      { name: "mattmccoy", local: true, drive: true, offline: false },
    ],
    unsorted: { local: 1, drive: 0 },
    unexpected: [{ library: "local", name: "Old Stuff" }],
    drive_connected: false,
    ...over,
  };
}

test("name rules match the backend lists", () => {
  for (const ok of VALID) assert.equal(collectionNameError(ok), null, ok);
  for (const bad of REJECTED) assert.ok(collectionNameError(bad), JSON.stringify(bad));
  // the backend's messages, verbatim (collections.py collection_name_error)
  assert.equal(collectionNameError(".x"), "A collection name cannot start with a dot.");
  assert.equal(collectionNameError("20261102_165506"), "A collection name cannot look like a run folder (YYYYMMDD_HHMMSS...).");
  assert.equal(collectionNameError("Bad Name"), "Use 1-40 characters: lowercase letters, digits, '-' and '_'.");
});

test("entries order and notes", () => {
  const e = pickerEntries(doc({
    collections: [
      { name: "rf-sintering", local: false, drive: true, offline: true },
      { name: "mattmccoy", local: true, drive: true, offline: false },
      { name: "zeta", local: false, drive: true, offline: false },
      { name: "beta", local: true, drive: false, offline: false },
    ],
  }));
  assert.deepEqual(e, [
    { value: "beta", label: "beta", disabled: false, note: "on this Mac only" },
    { value: "mattmccoy", label: "mattmccoy", disabled: false, note: null },
    { value: "rf-sintering", label: "rf-sintering", disabled: false, note: "offline" },
    { value: "zeta", label: "zeta", disabled: false, note: "on drive only" },
    { value: "", label: "Unsorted (1)", disabled: false, note: null },
    { value: "local:Old Stuff", label: "Old Stuff", disabled: true, note: "not a collection or run; left untouched" },
  ]);
  // Unsorted counts both sides
  const u = pickerEntries(doc({ unsorted: { local: 2, drive: 3 } })).find((x) => x.value === "");
  assert.equal(u?.label, "Unsorted (5)");
});

test("Unsorted hidden when empty and not selected", () => {
  const empty = { unsorted: { local: 0, drive: 0 } };
  assert.equal(pickerEntries(doc(empty)).some((x) => x.value === ""), false);
  assert.equal(pickerEntries(doc({ ...empty, selected: null })).some((x) => x.value === ""), false);
  const sel = pickerEntries(doc({ ...empty, selected: "" })).find((x) => x.value === "");
  assert.equal(sel?.label, "Unsorted (0)");
});

test("canRecord blocks null and Unsorted, allows an offline-only collection (ruling R1)", () => {
  const reason = "pick a collection before recording";
  assert.deepEqual(canRecord(doc({ selected: null })), { ok: false, reason });
  assert.deepEqual(canRecord(doc({ selected: "" })), { ok: false, reason });
  assert.deepEqual(canRecord(doc({ selected: "mattmccoy" })), { ok: true, reason: null });
  // the operator records an offline-only collection to the Mac and creates the folder
  assert.deepEqual(canRecord(doc({ selected: "rf-sintering" })), { ok: true, reason: null });
});

test("collectionLabel names the selection, Unsorted, or none", () => {
  assert.equal(collectionLabel("mattmccoy"), "mattmccoy");
  assert.equal(collectionLabel(""), "Unsorted");
  assert.equal(collectionLabel(null), "no collection");
});

test("the picker locks while recording or armed", () => {
  assert.equal(pickerLocked(null), false);
  assert.equal(pickerLocked({ state: "idle" }), false);
  assert.equal(pickerLocked({ state: "recording" }), true);
  assert.equal(pickerLocked({ state: "armed" }), true);
  assert.equal(PICKER_LOCK_MESSAGE, "the collection can't change while a recording or armed trigger is active");
});
