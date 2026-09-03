/** Ramer–Douglas–Peucker path simplification for freehand ROIs (pixel units). */
export type P = [number, number];

function perpDist(p: P, a: P, b: P): number {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  if (len2 === 0) return Math.hypot(p[0] - a[0], p[1] - a[1]);
  const t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2;
  const cx = a[0] + t * dx, cy = a[1] + t * dy;
  return Math.hypot(p[0] - cx, p[1] - cy);
}

export function simplifyPath(pts: P[], tol: number): P[] {
  if (pts.length <= 2) return pts.slice();
  let maxD = -1, idx = 0;
  const a = pts[0], b = pts[pts.length - 1];
  for (let i = 1; i < pts.length - 1; i++) { const d = perpDist(pts[i], a, b); if (d > maxD) { maxD = d; idx = i; } }
  if (maxD > tol) {
    const left = simplifyPath(pts.slice(0, idx + 1), tol), right = simplifyPath(pts.slice(idx), tol);
    return [...left.slice(0, -1), ...right];
  }
  return [a, b];
}
