/**
 * Planar homography between the visible and IR images.
 *
 * The cameras are not coaxial, so a scale/shift can only align one point; a homography aligns
 * the whole *plane* the correspondences lie on (the sample surface at its working distance).
 * Off-plane objects still show parallax. Coordinates are normalised (0..1 of each image).
 */

export type Pt = [number, number];
export type H3 = number[][]; // 3×3, h33 = 1

/** Solves A x = b (n×n) by Gaussian elimination with partial pivoting; null when singular. */
export function solveLinear(A: number[][], b: number[]): number[] | null {
  const n = b.length;
  const M = A.map((row, i) => [...row, b[i]]);
  for (let col = 0; col < n; col++) {
    let piv = col;
    for (let r = col + 1; r < n; r++) if (Math.abs(M[r][col]) > Math.abs(M[piv][col])) piv = r;
    if (Math.abs(M[piv][col]) < 1e-12) return null;
    [M[col], M[piv]] = [M[piv], M[col]];
    for (let r = 0; r < n; r++) {
      if (r === col) continue;
      const f = M[r][col] / M[col][col];
      for (let c = col; c <= n; c++) M[r][c] -= f * M[col][c];
    }
  }
  return M.map((row, i) => row[n] / row[i]);
}

/**
 * Direct linear transform: least-squares H mapping src → dst from ≥ 4 pairs (normal equations of
 * the 2n×8 system with h33 fixed to 1). Null for < 4 pairs or a degenerate configuration.
 */
export function fitHomography(src: Pt[], dst: Pt[]): H3 | null {
  const n = Math.min(src.length, dst.length);
  if (n < 4) return null;
  const rows: number[][] = [];
  const rhs: number[] = [];
  for (let i = 0; i < n; i++) {
    const [x, y] = src[i], [u, v] = dst[i];
    rows.push([x, y, 1, 0, 0, 0, -u * x, -u * y]); rhs.push(u);
    rows.push([0, 0, 0, x, y, 1, -v * x, -v * y]); rhs.push(v);
  }
  // normal equations AᵀA h = Aᵀb
  const AtA = Array.from({ length: 8 }, () => new Array<number>(8).fill(0));
  const Atb = new Array<number>(8).fill(0);
  for (let r = 0; r < rows.length; r++) {
    for (let i = 0; i < 8; i++) {
      Atb[i] += rows[r][i] * rhs[r];
      for (let j = 0; j < 8; j++) AtA[i][j] += rows[r][i] * rows[r][j];
    }
  }
  const h = solveLinear(AtA, Atb);
  if (!h || h.some((v) => !Number.isFinite(v))) return null;
  const z = (v: number) => (v === 0 ? 0 : v); // no -0 (JSON round-trips would differ)
  return [[z(h[0]), z(h[1]), z(h[2])], [z(h[3]), z(h[4]), z(h[5])], [z(h[6]), z(h[7]), 1]];
}

export function applyH(H: H3, [x, y]: Pt): Pt {
  const w = H[2][0] * x + H[2][1] * y + H[2][2];
  return [(H[0][0] * x + H[0][1] * y + H[0][2]) / w, (H[1][0] * x + H[1][1] * y + H[1][2]) / w];
}

/** Root-mean-square distance between H(src) and dst, in the same normalised units. */
export function rmsResidual(H: H3, src: Pt[], dst: Pt[]): number {
  const n = Math.min(src.length, dst.length);
  if (n === 0) return 0;
  let s = 0;
  for (let i = 0; i < n; i++) { const p = applyH(H, src[i]); s += (p[0] - dst[i][0]) ** 2 + (p[1] - dst[i][1]) ** 2; }
  return Math.sqrt(s / n);
}

/**
 * CSS transform applying a normalised homography to an element of w×h pixels laid over the
 * target image box (use with `transform-origin: 0 0`). Hpx = S·H·S⁻¹ with S = diag(w, h, 1).
 */
export function toCssMatrix3d(H: H3, w: number, h: number): string {
  const a = H[0][0], b = H[0][1] * (w / h), c = H[0][2] * w;
  const d = H[1][0] * (h / w), e = H[1][1], f = H[1][2] * h;
  const g = H[2][0] / w, i = H[2][1] / h, j = H[2][2];
  // column-major matrix3d: columns are the images of (x, y, z, 1)
  const m = [a, d, 0, g, b, e, 0, i, 0, 0, 1, 0, c, f, 0, j];
  return `matrix3d(${m.map((v) => Number(v.toFixed(8))).join(",")})`;
}
