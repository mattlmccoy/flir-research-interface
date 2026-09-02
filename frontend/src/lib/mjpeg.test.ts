import { test } from "node:test";
import assert from "node:assert/strict";
import { extractJpegs } from "./mjpeg.ts";

const SOI = Uint8Array.from([0xff, 0xd8]);
const EOI = Uint8Array.from([0xff, 0xd9]);
const jpeg = (body: number[]) => Uint8Array.from([...SOI, ...body, ...EOI]);
const cat = (...parts: Uint8Array[]) => { const n = parts.reduce((s, p) => s + p.length, 0); const out = new Uint8Array(n); let o = 0; for (const p of parts) { out.set(p, o); o += p.length; } return out; };
const hdr = new TextEncoder().encode("--ffmpeg\r\nContent-type: image/jpeg\r\nContent-length: 5\r\n\r\n");

test("extractJpegs pulls complete JPEGs out of the multipart stream and keeps the remainder", () => {
  const a = jpeg([1, 2, 3]), b = jpeg([4]);
  const stream = cat(hdr, a, hdr, b, hdr, SOI, Uint8Array.from([9]));
  const { frames, rest } = extractJpegs(stream);
  assert.equal(frames.length, 2);
  assert.deepEqual(Array.from(frames[0]), Array.from(a));
  assert.deepEqual(Array.from(frames[1]), Array.from(b));
  // the partial third frame (SOI + 1 byte, no EOI) stays for the next call
  assert.deepEqual(Array.from(rest), [0xff, 0xd8, 9]);
});

test("extractJpegs ignores a stray EOI before any SOI and handles an empty buffer", () => {
  assert.deepEqual(extractJpegs(new Uint8Array(0)), { frames: [], rest: new Uint8Array(0) });
  const { frames, rest } = extractJpegs(cat(EOI, hdr, jpeg([7])));
  assert.equal(frames.length, 1);
  assert.equal(rest.length, 0);
});
