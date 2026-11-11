import { test } from "node:test";
import assert from "node:assert/strict";
import { keyOf, parseRunKey, runKey, runName, runPath } from "./runKey.ts";

test("runKey round-trips and top level stays bare", () => {
  assert.equal(runKey("mattmccoy", "20261102_165506_Run"), "mattmccoy/20261102_165506_Run");
  assert.equal(runKey(null, "20261102_165506_Run"), "20261102_165506_Run");
  assert.deepEqual(parseRunKey("mattmccoy/20261102_165506_Run"), { collection: "mattmccoy", name: "20261102_165506_Run" });
});

test("runPath adds the collection after any query", () => {
  assert.equal(runPath("mattmccoy/r", "/frames?start=0&count=5"), "/api/experiments/r/frames?start=0&count=5&collection=mattmccoy");
  assert.equal(runPath("r"), "/api/experiments/r?collection=");
  assert.equal(runPath("rf-sintering/a b", "/reveal"), "/api/experiments/a%20b/reveal?collection=rf-sintering");
});

test("a bare key parses to the top level; runName and keyOf agree with runKey", () => {
  assert.deepEqual(parseRunKey("20261102_165506_Run"), { collection: null, name: "20261102_165506_Run" });
  assert.equal(runKey(undefined, "r"), "r");
  assert.equal(runKey("", "r"), "r", "an empty collection is the top level");
  assert.equal(runName("mattmccoy/r"), "r");
  assert.equal(runName("r"), "r");
  assert.equal(keyOf({ collection: "mattmccoy", name: "r" }), "mattmccoy/r");
  assert.equal(keyOf({ name: "r" }), "r");
  assert.equal(keyOf({ collection: null, name: "r" }), "r");
});
