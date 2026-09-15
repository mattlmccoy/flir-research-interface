import { test } from "node:test";
import assert from "node:assert/strict";
import { storageBreakdown, summaryLabel, type Located } from "./storageSummary.ts";

const items: Located[] = [
  { library: "local", size_bytes: 2_000_000_000 },
  { library: "local", size_bytes: 1_000_000_000 },
  { library: "drive", size_bytes: 5_000_000_000 },
  { library: undefined, size_bytes: 500_000_000 }, // no library => counts as local
];

test("splits bytes and counts by location; missing library is local", () => {
  const b = storageBreakdown(items);
  assert.equal(b.total, 4);
  assert.equal(b.localCount, 3);
  assert.equal(b.driveCount, 1);
  assert.equal(b.localBytes, 3_500_000_000);
  assert.equal(b.driveBytes, 5_000_000_000);
});

test("label shows local usage; adds drive only when a drive is connected", () => {
  const b = storageBreakdown(items);
  // moving a run local->drive must lower the local figure, which is the whole point of offload
  assert.match(summaryLabel(b, false), /4 experiments/);
  assert.match(summaryLabel(b, false), /3\.50 GB local/);
  assert.doesNotMatch(summaryLabel(b, false), /drive/);
  assert.match(summaryLabel(b, true), /5\.00 GB on drive/);
});

test("empty list is handled", () => {
  const b = storageBreakdown([]);
  assert.equal(b.total, 0);
  assert.equal(summaryLabel(b, false), "0 experiments");
});
