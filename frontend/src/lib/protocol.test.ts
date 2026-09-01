import { test } from "node:test";
import assert from "node:assert/strict";
import { decodeFrameMessage } from "./protocol.ts";

function build(header: object, counts: Uint16Array): ArrayBuffer {
  const h = new TextEncoder().encode(JSON.stringify(header));
  const buf = new ArrayBuffer(4 + h.length + counts.length * 2);
  const view = new DataView(buf);
  view.setUint32(0, h.length, false);
  new Uint8Array(buf, 4, h.length).set(h);
  for (let i = 0; i < counts.length; i++) view.setUint16(4 + h.length + i * 2, counts[i], true);
  return buf;
}

test("decodeFrameMessage returns header and little-endian uint16 counts", () => {
  const header = { type: "frame", frame_id: 3, width: 3, height: 2, kelvin_per_count: 0.01, kelvin_offset: 273.15 };
  const counts = new Uint16Array([1, 2, 3, 4, 5, 65535]);
  const msg = decodeFrameMessage(build(header, counts));
  assert.equal(msg.header.frame_id, 3);
  assert.deepEqual(Array.from(msg.counts), Array.from(counts));
});

test("decodeFrameMessage rejects a payload whose size mismatches width*height", () => {
  const header = { type: "frame", frame_id: 1, width: 3, height: 2 };
  assert.throws(() => decodeFrameMessage(build(header, new Uint16Array([1, 2]))), /payload/);
});
