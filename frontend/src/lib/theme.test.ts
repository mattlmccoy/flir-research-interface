import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(join(here, "..", "theme.css"), "utf8");

const REQUIRED = [
  "--bg", "--bg-deep", "--panel", "--line", "--fg", "--fg-strong", "--muted",
  "--accent", "--live", "--err", "--rec", "--font-ui", "--font-mono",
];

test("theme.css defines every token from the spec on :root", () => {
  for (const t of REQUIRED) assert.match(css, new RegExp(`${t}\\s*:`), `${t} missing`);
});

test("theme.css self-hosts IBM Plex (no Google Fonts URLs)", () => {
  assert.match(css, /@font-face[^}]*IBM Plex Sans/);
  assert.match(css, /@font-face[^}]*IBM Plex Mono/);
  assert.doesNotMatch(css, /fonts\.googleapis\.com|fonts\.gstatic\.com/);
});

test("live green and accent amber are the spec values", () => {
  assert.match(css, /--live:\s*#5cff8a/i);
  assert.match(css, /--accent:\s*#ffb454/i);
});
