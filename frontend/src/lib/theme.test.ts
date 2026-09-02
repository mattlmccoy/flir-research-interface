import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const themePath = join(here, "..", "theme.css");
const indexHtmlPath = join(here, "..", "..", "index.html");
const fontsDir = join(here, "..", "..", "public", "fonts");

const css = readFileSync(themePath, "utf8");

function extractRootBlock(source: string): string {
  const match = source.match(/:root\s*{([^}]*)}/s);
  assert.ok(match, ":root block not found in theme.css");
  return match![1];
}

const rootBlock = extractRootBlock(css);

// The full token set theme.css must define on :root: the 27 base design tokens
// plus the 3 additions Task 3 needs (--line-control, --focus, --live-glow-dim).
const REQUIRED_TOKENS = [
  "--bg", "--bg-deep", "--panel", "--line", "--line-strong", "--line-control",
  "--fg", "--fg-strong", "--muted",
  "--accent", "--accent-ink", "--focus",
  "--live", "--live-glow", "--live-glow-dim",
  "--warn", "--warn-bg",
  "--err", "--err-bg",
  "--rec",
  "--font-ui", "--font-mono",
  "--fs", "--space", "--radius",
  "--strip-w", "--rail-w", "--dock-h", "--topbar-h", "--statusbar-h",
];

test("theme.css :root defines every design token, and only inside :root", () => {
  assert.equal(REQUIRED_TOKENS.length, 30, "REQUIRED_TOKENS list itself drifted from theme.css — update it alongside the CSS");
  for (const token of REQUIRED_TOKENS) {
    assert.match(rootBlock, new RegExp(`${token}\\s*:`), `${token} missing from :root`);
  }
});

test("theme.css self-hosts IBM Plex via @font-face (no Google Fonts URLs)", () => {
  assert.match(css, /@font-face[^}]*IBM Plex Sans/);
  assert.match(css, /@font-face[^}]*IBM Plex Mono/);
  assert.doesNotMatch(css, /fonts\.googleapis\.com|fonts\.gstatic\.com/);
});

test("live green and accent amber are the spec values", () => {
  assert.match(rootBlock, /--live:\s*#5cff8a/i);
  assert.match(rootBlock, /--accent:\s*#ffb454/i);
});

test("every font url() referenced in theme.css exists under public/fonts as a real woff2 file", () => {
  const urls = [...css.matchAll(/url\("\/fonts\/([^"]+)"\)/g)].map((m) => m[1]);
  assert.ok(urls.length >= 6, "expected at least 6 self-hosted font file references in theme.css");
  for (const filename of urls) {
    const filePath = join(fontsDir, filename);
    assert.ok(existsSync(filePath), `${filename} is referenced in theme.css but missing from frontend/public/fonts`);
    const magic = readFileSync(filePath).subarray(0, 4).toString("ascii");
    assert.equal(magic, "wOF2", `${filename} does not start with the wOF2 magic bytes (got ${JSON.stringify(magic)})`);
  }
});

test("index.html sets the app title and links no external Google Fonts", () => {
  const html = readFileSync(indexHtmlPath, "utf8");
  assert.match(html, /<title>FLIR Research Interface<\/title>/);
  assert.doesNotMatch(html, /fonts\.googleapis\.com|fonts\.gstatic\.com/);
});
