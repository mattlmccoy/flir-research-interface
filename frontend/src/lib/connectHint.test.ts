import { test } from "node:test";
import assert from "node:assert/strict";
import { connectHint } from "./connectHint.ts";

// Shapes as GET /api/camera/status returns them (backend tests/test_api_connect_hint.py); the
// error text is the real Spinnaker -1023 line from backend/tests/fixtures/neterr/.
const RAW_1023 = "Spinnaker: Spinnaker: Camera is on an adapter with conflicting IP and subnet address range. [-1023]";
const HINT_1023 = {
  kind: "subnet_conflict",
  message: "Camera can't connect: adapter AX88179A (en15) is 192.168.9.1/16, which overlaps the camera adapter USB 10/100/1000 LAN (en13, 192.168.8.1/24). Narrow it to /24 in Terminal:",
  command: 'sudo networksetup -setmanual "AX88179A" 192.168.9.1 255.255.255.0',
};

test("connectHint: nothing when healthy, or from an operator without the field", () => {
  assert.equal(connectHint({ state: "acquiring", last_error: null, last_error_hint: null }), null);
  assert.equal(connectHint({ state: "disconnected" }), null);
  assert.equal(connectHint({ state: "error", last_error: "boom" }), null); // raw-only stays as before
});

test("connectHint: a failed connect shows the plain message, the command and the raw error", () => {
  const h = connectHint({ state: "disconnected", last_error: RAW_1023, last_error_hint: HINT_1023 });
  assert.ok(h);
  assert.equal(h.level, "err");
  assert.equal(h.message, HINT_1023.message);
  assert.equal(h.command, HINT_1023.command);
  assert.equal(h.raw, RAW_1023);
  assert.equal(h.short, "subnet conflict");
});

test("connectHint: while reconnecting it is a warning; a removed adapter has no command", () => {
  const h = connectHint({
    state: "reconnecting",
    last_error: "CameraError: Spinnaker: Camera has been removed from the list and is no longer valid. [-1024]; reconnecting in 2s",
    last_error_hint: { kind: "adapter_removed", message: "The camera's network adapter disappeared from the USB bus — power-cycle the Anker USB-C hub.", command: null },
  });
  assert.ok(h);
  assert.equal(h.level, "warn");
  assert.equal(h.command, null);
  assert.equal(h.short, "adapter gone");
});

test("connectHint: a malformed hint is ignored rather than rendered", () => {
  assert.equal(connectHint({ state: "disconnected", last_error: "x", last_error_hint: { kind: "subnet_conflict" } as never }), null);
});
