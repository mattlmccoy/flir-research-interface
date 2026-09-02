import { test } from "node:test";
import assert from "node:assert/strict";
import { apiUrl, checkHandshake, loadOperatorBase, saveOperatorBase, wsUrl, normalizeBase } from "./operator.ts";

function storage(init: Record<string, string> = {}): Storage {
  const m = new Map(Object.entries(init));
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => { m.set(k, v); }, removeItem: (k: string) => { m.delete(k); } } as unknown as Storage;
}

test("normalizeBase strips trailing slashes and rejects non-http", () => {
  assert.equal(normalizeBase("http://localhost:8000/"), "http://localhost:8000");
  assert.equal(normalizeBase("  https://cam.local:8443//  "), "https://cam.local:8443");
  assert.equal(normalizeBase(""), "");
  assert.equal(normalizeBase("ftp://x"), null);
  assert.equal(normalizeBase("javascript:alert(1)"), null);
});

test("operator base: same-origin when served by the operator, localhost:8000 in site mode", () => {
  assert.equal(loadOperatorBase(storage(), { siteMode: false }), "");
  assert.equal(loadOperatorBase(storage(), { siteMode: true }), "http://localhost:8000");
  const st = storage();
  saveOperatorBase(st, "http://127.0.0.1:9000/");
  assert.equal(loadOperatorBase(st, { siteMode: true }), "http://127.0.0.1:9000");
  assert.equal(loadOperatorBase(storage({ "fri.operator.v1": "garbage" }), { siteMode: true }), "http://localhost:8000");
});

test("apiUrl and wsUrl derive from the base", () => {
  assert.equal(apiUrl("", "/api/health"), "/api/health");
  assert.equal(apiUrl("http://localhost:8000", "/api/health"), "http://localhost:8000/api/health");
  assert.equal(wsUrl("http://localhost:8000", "/ws/frames"), "ws://localhost:8000/ws/frames");
  assert.equal(wsUrl("https://cam.local", "/ws/frames"), "wss://cam.local/ws/frames");
  assert.equal(wsUrl("", "/ws/frames", { protocol: "https:", host: "app.example" }), "wss://app.example/ws/frames");
});

test("checkHandshake: major mismatch refuses, minor mismatch warns, same is ok", () => {
  assert.deepEqual(checkHandshake("1.0", "1.0"), { level: "ok" });
  assert.deepEqual(checkHandshake("1.0", "1.2"), { level: "warn", message: "operator API 1.2 differs from UI 1.0 (minor); some features may be missing" });
  assert.equal(checkHandshake("1.0", "2.0").level, "refuse");
  assert.equal(checkHandshake("1.0", undefined).level, "refuse");
});
