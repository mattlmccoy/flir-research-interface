import { test } from "node:test";
import assert from "node:assert/strict";
import { detectPlatform, installerFor, installSteps } from "./platform.ts";

test("detectPlatform recognises macOS (arm64 assumed on modern Macs), Windows and Linux", () => {
  assert.equal(detectPlatform("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605", "MacIntel"), "macos");
  assert.equal(detectPlatform("Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Win32"), "windows");
  assert.equal(detectPlatform("Mozilla/5.0 (X11; Linux x86_64)", "Linux x86_64"), "linux");
  assert.equal(detectPlatform("something else", ""), "unknown");
});

test("installerFor returns a label and note for every platform and never an empty label", () => {
  for (const p of ["macos", "windows", "linux", "unknown"] as const) {
    const i = installerFor(p);
    assert.ok(i.label.length > 0 && i.note.length > 0);
  }
  assert.match(installerFor("macos").label, /macOS/);
  assert.match(installerFor("windows").label, /Windows/);
});

test("installSteps: macOS gets the one-line installer; others get the manual route", () => {
  const mac = installSteps("macos");
  assert.ok(mac.command?.startsWith("curl -fsSL https://raw.githubusercontent.com/mattlmccoy/flir-research-interface/main/install.sh"));
  assert.ok(mac.command?.endsWith("| bash"));
  assert.ok(mac.steps.length >= 3);
  const win = installSteps("windows");
  assert.ok(win.command?.startsWith("irm https://raw.githubusercontent.com/mattlmccoy/flir-research-interface/main/install.ps1"));
  assert.ok(win.command?.endsWith("| iex"));
  assert.ok(installSteps("linux").command?.endsWith("| bash"));
});
