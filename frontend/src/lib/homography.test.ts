import { test } from "node:test";
import assert from "node:assert/strict";
import { applyH, fitHomography, rmsResidual, toCssMatrix3d, type Pt } from "./homography.ts";

const near = (a: number, b: number, tol = 1e-6) => assert.ok(Math.abs(a - b) < tol, `${a} vs ${b}`);

test("fitHomography recovers a pure scale + translation from 4 exact pairs", () => {
  const src: Pt[] = [[0, 0], [1, 0], [1, 1], [0, 1]];
  const dst: Pt[] = src.map(([x, y]) => [0.5 * x + 0.1, 0.5 * y + 0.2]);
  const H = fitHomography(src, dst);
  assert.ok(H);
  for (let i = 0; i < 4; i++) { const p = applyH(H, src[i]); near(p[0], dst[i][0]); near(p[1], dst[i][1]); }
  near(rmsResidual(H, src, dst), 0, 1e-9);
});

test("fitHomography recovers a perspective (keystone) mapping and least-squares fits 6 noisy pairs", () => {
  // a genuinely projective H (h31, h32 ≠ 0), normalised so h33 = 1
  const Htrue = [[0.9, 0.05, 0.1], [-0.02, 1.1, 0.05], [0.15, -0.1, 1]];
  const map = ([x, y]: Pt): Pt => { const w = Htrue[2][0] * x + Htrue[2][1] * y + 1; return [(Htrue[0][0] * x + Htrue[0][1] * y + Htrue[0][2]) / w, (Htrue[1][0] * x + Htrue[1][1] * y + Htrue[1][2]) / w]; };
  const src: Pt[] = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9], [0.5, 0.5], [0.3, 0.7]];
  const dst = src.map(map);
  const H = fitHomography(src, dst);
  assert.ok(H);
  for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) near(H[r][c], Htrue[r][c], 1e-6);
  const noisy = dst.map(([x, y], i) => [x + (i % 2 ? 0.002 : -0.002), y + (i % 3 ? -0.001 : 0.001)] as Pt);
  const Hn = fitHomography(src, noisy);
  assert.ok(Hn);
  assert.ok(rmsResidual(Hn, src, noisy) < 0.004);
  assert.ok(rmsResidual(Hn, src, dst) < 0.004);
});

test("fitHomography refuses fewer than 4 pairs or degenerate (collinear) pairs", () => {
  assert.equal(fitHomography([[0, 0], [1, 0], [1, 1]], [[0, 0], [1, 0], [1, 1]]), null);
  assert.equal(fitHomography([[0, 0], [1, 1], [2, 2], [3, 3]], [[0, 0], [1, 1], [2, 2], [3, 3]]), null);
});

test("toCssMatrix3d expresses the normalised homography in element pixels, origin top-left", () => {
  const H = [[0.5, 0, 0.1], [0, 0.5, 0.2], [0, 0, 1]];
  const css = toCssMatrix3d(H, 800, 600);
  assert.match(css, /^matrix3d\(/);
  const nums = css.slice(9, -1).split(",").map(Number);
  assert.equal(nums.length, 16);
  // column-major: m11=0.5 (x scale), m22=0.5, translation tx = 0.1*800 = 80, ty = 0.2*600 = 120
  near(nums[0], 0.5); near(nums[5], 0.5); near(nums[12], 80); near(nums[13], 120); near(nums[15], 1);
});
