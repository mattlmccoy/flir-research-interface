import { test } from "node:test";
import assert from "node:assert/strict";
import { decodeFrameBlock, decodeFrameMessage } from "./protocol.ts";

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

test("fast path: decodeFrameMessage handles both aligned and odd header offsets", () => {
  for (const pad of [0, 1, 2, 3]) {  // vary header length parity
    const name = "x".repeat(pad);
    const header = JSON.stringify({ type: "frame", width: 2, height: 2, name });
    const hb = new TextEncoder().encode(header);
    const buf = new ArrayBuffer(4 + hb.length + 8);
    const dv = new DataView(buf);
    dv.setUint32(0, hb.length, false);
    new Uint8Array(buf, 4, hb.length).set(hb);
    const vals = [10, 300, 65535, 1];
    for (let i = 0; i < 4; i++) dv.setUint16(4 + hb.length + i * 2, vals[i], true);
    const m = decodeFrameMessage(buf);
    assert.deepEqual(Array.from(m.counts), vals, `pad ${pad}`);
  }
});

test("decodeFrameBlock splits a concatenated [len][msg] body into frames", () => {
  const one = (id: number) => {
    const header = JSON.stringify({ type: "frame", width: 1, height: 1, frame_id: id });
    const hb = new TextEncoder().encode(header);
    const b = new ArrayBuffer(4 + hb.length + 2);
    const dv = new DataView(b);
    dv.setUint32(0, hb.length, false);
    new Uint8Array(b, 4, hb.length).set(hb);
    dv.setUint16(4 + hb.length, id + 100, true);
    return new Uint8Array(b);
  };
  const a = one(0), c = one(1);
  const body = new ArrayBuffer(4 + a.length + 4 + c.length);
  const dv = new DataView(body);
  let off = 0;
  for (const part of [a, c]) { dv.setUint32(off, part.length, false); off += 4; new Uint8Array(body, off, part.length).set(part); off += part.length; }
  const frames = decodeFrameBlock(body);
  assert.equal(frames.length, 2);
  assert.equal(frames[0].header.frame_id, 0);
  assert.equal(frames[1].counts[0], 101);
});
