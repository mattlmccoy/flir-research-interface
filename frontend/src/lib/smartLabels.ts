// Smart ROI label crop wire format (see backend analysis/smart_wire.py): row-major run-length
// pairs (uint8 value, uint32 little-endian run), base64. 0 none, 1 sample, 2.. rings.

export type SmartOverlay = {
  id: number;
  state: "searching" | "locked" | "holding";
  valid: boolean;
  bbox: [number, number, number, number] | null;
  labels: string | null;
  /** Present while the sample or a ring has over-range pixels: the bounded readings for display
   *  (smartReadout.ts parseSmartOver; backend smart_wire.smart_overlay). Never in the TC-POWER feed. */
  over?: unknown;
};

export function decodeLabels(b64: string, w: number, h: number): Uint8Array {
  const bin = atob(b64);
  if (bin.length % 5 !== 0) throw new Error("smart labels: truncated run-length data");
  const out = new Uint8Array(w * h);
  let pos = 0;
  for (let i = 0; i < bin.length; i += 5) {
    const value = bin.charCodeAt(i);
    const run =
      (bin.charCodeAt(i + 1) |
        (bin.charCodeAt(i + 2) << 8) |
        (bin.charCodeAt(i + 3) << 16) |
        (bin.charCodeAt(i + 4) << 24)) >>>
      0;
    if (pos + run > out.length) throw new Error("smart labels: runs exceed w*h");
    out.fill(value, pos, pos + run);
    pos += run;
  }
  if (pos !== out.length) throw new Error("smart labels: runs do not fill w*h");
  return out;
}

/** Edge pixels: a labelled pixel with a 4-neighbour that is unlabelled (0) or has a higher label,
 * i.e. the inner side of each boundary (value = its own label). A neighbour outside the crop
 * counts as 0, so labelled pixels on the crop border are edges (the crop is the bbox of labels>0,
 * so the outermost ring sits on the border). */
export function labelEdges(
  labels: Uint8Array,
  w: number,
  h: number,
): { value: number; idx: number }[] {
  const edges: { value: number; idx: number }[] = [];
  const outer = (v: number, n: number) => n === 0 || n > v;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      const v = labels[i];
      if (v === 0) continue;
      if (
        x === 0 || x === w - 1 || y === 0 || y === h - 1 ||
        outer(v, labels[i - 1]) || outer(v, labels[i + 1]) ||
        outer(v, labels[i - w]) || outer(v, labels[i + w])
      ) {
        edges.push({ value: v, idx: i });
      }
    }
  }
  return edges;
}
