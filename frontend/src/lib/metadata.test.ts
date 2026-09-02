import { test } from "node:test";
import assert from "node:assert/strict";
import { parseValue } from "./metadata.ts";

test("parseValue: numeric strings become numbers, blanks delete, text stays text", () => {
  assert.equal(parseValue("400"), 400);
  assert.equal(parseValue(" -3.5 "), -3.5);
  assert.equal(parseValue("1e3"), 1000);
  assert.equal(parseValue(""), null);
  assert.equal(parseValue("   "), null);
  assert.equal(parseValue("PA12"), "PA12");
  assert.equal(parseValue("13.56 MHz"), "13.56 MHz");
  assert.equal(parseValue("007"), 7);
});
