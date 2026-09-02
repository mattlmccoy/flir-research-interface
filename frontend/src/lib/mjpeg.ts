/**
 * Browser-side MJPEG (multipart/x-mixed-replace) frame extraction. The page fetches the
 * stream itself (so it can abort it deterministically) and paints each JPEG into an <img>.
 */

const SOI0 = 0xff, SOI1 = 0xd8, EOI0 = 0xff, EOI1 = 0xd9;

/** Complete JPEGs found in `buf` (SOI…EOI, inclusive) and the unconsumed tail. */
export function extractJpegs(buf: Uint8Array): { frames: Uint8Array[]; rest: Uint8Array } {
  const frames: Uint8Array[] = [];
  let pos = 0;
  for (;;) {
    let start = -1;
    for (let i = pos; i + 1 < buf.length; i++) if (buf[i] === SOI0 && buf[i + 1] === SOI1) { start = i; break; }
    if (start < 0) return { frames, rest: new Uint8Array(0) };
    let end = -1;
    for (let i = start + 2; i + 1 < buf.length; i++) if (buf[i] === EOI0 && buf[i + 1] === EOI1) { end = i + 2; break; }
    if (end < 0) return { frames, rest: buf.slice(start) };
    frames.push(buf.slice(start, end));
    pos = end;
  }
}

export function concat(a: Uint8Array, b: Uint8Array): Uint8Array {
  if (a.length === 0) return b;
  const out = new Uint8Array(a.length + b.length);
  out.set(a, 0); out.set(b, a.length);
  return out;
}

/**
 * Streams `url` and calls `onFrame` with each JPEG as a Blob. Returns a stop function that
 * aborts the request (which ends the operator's transcode).
 */
export function streamMjpeg(url: string, onFrame: (jpeg: Blob) => void, onEnd: (err: string | null) => void): () => void {
  const ac = new AbortController();
  (async () => {
    try {
      const res = await fetch(url, { signal: ac.signal, cache: "no-store" });
      if (!res.ok || !res.body) { onEnd(`${res.status} ${await res.text().catch(() => "")}`.trim()); return; }
      const reader = res.body.getReader();
      let rest: Uint8Array = new Uint8Array(0);
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        const parsed = extractJpegs(concat(rest, value));
        rest = parsed.rest;
        const last = parsed.frames[parsed.frames.length - 1]; // only the newest matters for a live view
        if (last) { const copy = new Uint8Array(last.length); copy.set(last); onFrame(new Blob([copy.buffer], { type: "image/jpeg" })); }
      }
      onEnd(null);
    } catch (e) {
      onEnd(ac.signal.aborted ? null : String(e));
    }
  })();
  return () => ac.abort();
}
