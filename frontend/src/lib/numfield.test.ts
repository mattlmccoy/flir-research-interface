import { test } from "node:test";
import assert from "node:assert/strict";
import { commitDraft } from "./numfield.ts";

test("commitDraft: empty string commits nothing; a valid number commits; junk is ignored", () => {
  assert.equal(commitDraft(""), null, "cleared field must not force a value");
  assert.equal(commitDraft("-"), null, "a lone minus while typing commits nothing");
  assert.equal(commitDraft("12"), 12);
  assert.equal(commitDraft("12.5"), 12.5);
  assert.equal(commitDraft("-3.2"), -3.2);
  assert.equal(commitDraft("abc"), null);
  assert.equal(commitDraft("0"), 0, "explicit zero is a valid value");
});
