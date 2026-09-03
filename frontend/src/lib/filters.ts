/** Display-only image filters (ResearchIR Filters toolbox subset). NaN pixels stay NaN and are
 * excluded from their neighbours' averages. Statistics always use the unfiltered field. */

/** Mean over a (2r+1)² window clipped to the image. */
export function boxBlur(f: Float32Array, w: number, h: number, r: number): Float32Array {
  const out = new Float32Array(f.length);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const k = y * w + x;
      if (Number.isNaN(f[k])) { out[k] = NaN; continue; }
      let sum = 0, n = 0;
      for (let yy = Math.max(0, y - r); yy <= Math.min(h - 1, y + r); yy++) {
        for (let xx = Math.max(0, x - r); xx <= Math.min(w - 1, x + r); xx++) {
          const v = f[yy * w + xx];
          if (!Number.isNaN(v)) { sum += v; n++; }
        }
      }
      out[k] = n ? sum / n : NaN;
    }
  }
  return out;
}

/** 3×3 median (edge windows are clipped), removes single-pixel spikes. */
export function median3(f: Float32Array, w: number, h: number): Float32Array {
  const out = new Float32Array(f.length);
  const buf: number[] = [];
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const k = y * w + x;
      if (Number.isNaN(f[k])) { out[k] = NaN; continue; }
      buf.length = 0;
      for (let yy = Math.max(0, y - 1); yy <= Math.min(h - 1, y + 1); yy++) {
        for (let xx = Math.max(0, x - 1); xx <= Math.min(w - 1, x + 1); xx++) {
          const v = f[yy * w + xx];
          if (!Number.isNaN(v)) buf.push(v);
        }
      }
      buf.sort((a, b) => a - b);
      out[k] = buf[buf.length >> 1];
    }
  }
  return out;
}

export type FilterName = "off" | "blur3" | "blur5" | "median3";
export const FILTER_NAMES: readonly FilterName[] = ["off", "blur3", "blur5", "median3"];
export function applyFilter(name: FilterName, f: Float32Array, w: number, h: number): Float32Array {
  switch (name) {
    case "blur3": return boxBlur(f, w, h, 1);
    case "blur5": return boxBlur(f, w, h, 2);
    case "median3": return median3(f, w, h);
    default: return f;
  }
}
