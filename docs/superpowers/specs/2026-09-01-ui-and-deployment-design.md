# FLIR Research Interface — UI system and deployment model

Date: 2026-09-01. Status: approved in brainstorming (visual companion session), pending review of
this written spec. Scope: the visual system, the Studio layout, the Experiments page, the
reveal-in-file-manager action, and the site + local-operator deployment model. Out of scope:
ROI/plot features themselves (Milestone 6), export (M7), visible camera (M9), LAN access (M10).

## 1. Decisions made

| Topic | Decision |
|---|---|
| Visual direction | "Instrument panel" (option A): dark charcoal, IBM Plex Sans for labels, IBM Plex Mono for all numbers and identifiers, one amber accent for data/controls, phosphor green reserved for *live* signals (status dot with glow, ROI outlines, primary plot trace), hairline dividers. Full wordmark "FLIR RESEARCH INTERFACE" in the header. |
| Live/playback layout | "Studio": left icon tool strip, center image (4:3, fills the free area), right rail with stacked sections, bottom plot dock with event markers, status bar. Strip, rail and dock are collapsible; all collapsed = image only. |
| Experiments page | Card grid with mid-capture thumbnail; hovering scrubs through keyframes; open / reveal / export actions; completeness badge. |
| Reveal | "Reveal" opens the experiment folder in Finder / Explorer / xdg file manager, performed by the local operator. |
| Deployment | One UI build deployed to GitHub Pages **and** embedded in the local operator. The site guides installation, auto-detects the operator, and then runs against it over localhost. Offline mode = operator-served copy + PWA cache. |
| SDK artifacts | The user hosts Spinnaker SDK and PySpin artifacts in a **private artifact location** (not in the git repository, not on the public Pages site); the installer downloads the platform-matching artifacts from a configurable URL. Decision and responsibility: project owner (internal, non-distributed tool). |

## 2. Visual system

### Tokens (CSS variables, single source in `frontend/src/theme.css`)

```
--bg        #101418   page
--bg-deep   #0b0e12   top bar, status bar, tool strip
--panel     #141920   rail, cards
--line      #232a33   hairlines
--fg        #d7dde5   text
--fg-strong #f5f7fa   headings, wordmark
--muted     #8b97a5   labels, secondary
--accent    #ffb454   amber: data values, primary buttons, active tab underline, hover readout
--live      #5cff8a   phosphor green: acquiring dot (+ 0 0 8px glow), ROI strokes, plot trace 1
--warn      #ffb454   (same hue as accent; warnings use a left border + tinted background)
--err       #ff5f56   errors, INCOMPLETE, recording drops
--rec       #ff5f56   REC indicator
--font-ui   "IBM Plex Sans", system-ui, sans-serif
--font-mono "IBM Plex Mono", ui-monospace, monospace
```

Fonts are self-hosted from `frontend/public/fonts/` (woff2), not fetched from Google at runtime,
so offline mode has the same look.

### Rules

- Every numeric value, identifier, path, serial, timestamp and unit is set in `--font-mono` with
  `font-variant-numeric: tabular-nums` so values do not jitter.
- Section headers in the rail: 10 px, uppercase, letter-spacing 0.14 em, `--muted`.
- Exactly one primary (amber) button per panel. Destructive/stop actions use `--err`.
- Green appears only when something is genuinely live: frames arriving, an ROI drawn on live
  data, a plot trace. Green never means "configured" or "ok" in a static sense.
- Status dot semantics: green + glow = acquiring and frames arriving in the last 2 s; amber =
  connected/no frames or reconnecting; red = error; grey = disconnected.
- Density: 13 px base, 4 px spacing grid; the image is the only large element.
- No animation except: status glow pulse (2 s), recording indicator blink (1 s), panel
  collapse/expand (120 ms). No decorative gradients, no scanlines.
- Light theme: not in scope (can be added later via tokens).

## 3. Studio layout

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ FLIR RESEARCH INTERFACE   live  experiments  setup        ● A70 · <serial> · acquiring  [disconnect] │
├──┬─────────────────────────────────────────────────────┬─────────────────────┤
│▣ │                                                     │ MEASUREMENTS        │
│○ │                                                     │ ROI 1 mean  176.33  │
│□ │                 thermal image (4:3)                 │ spot 1       21.47  │
│╱ │            hover readout · ROI overlays             │ frame max   187.42  │
│▤ │                 colour bar (right edge)             │ CAMERA              │
│⚙ │                                                     │ case  -20…250 °C    │
│N │                                                     │ ε 0.95  T_refl 20.0 │
│  ├─────────────────────────────────────────────────────┤ NUC auto  [NUC now] │
│  │ temperature vs time  (traces per ROI/spot, events)  │ EXPERIMENT          │
│  │                                                     │ material PA12 …     │
│  │                                                     │ [● REC]             │
├──┴─────────────────────────────────────────────────────┴─────────────────────┤
│ cam 30.0 fps  disp 14.9 fps  rx 4325  drop 0     ● REC 00:42   3.3 GB free   │
└──────────────────────────────────────────────────────────────────────────────┘
```

- **Tool strip** (left, 40 px): select, spot, rectangle, line (future), palette/range, camera
  controls, NUC. The active tool is amber-outlined. Tools that need M6 are present but disabled
  until implemented (never hidden, so the layout does not shift between releases).
- **Image**: letterboxed 4:3 inside the center cell; hover readout top-left; colour bar with min/max
  labels along the right edge inside the cell; ROI overlays drawn on a canvas layer above the image.
- **Right rail** (300 px, collapsible to 0): collapsible sections MEASUREMENTS, CAMERA, EXPERIMENT,
  RECORDING, DISPLAY (palette, AUTO/LOCKED range, manual min/max). Camera section writes camera
  nodes (case, object parameters, NUC mode, frame rate, noise reduction); while recording these
  controls are disabled and show "locked during recording" (brief §30). The DISPLAY section is
  visibly labelled "visualization only".
- **Plot dock** (bottom of the center cell, default 220 px, collapsible): temperature vs time for
  selected traces, event markers (RF ON/OFF, NUC, range switch), zoom/pan/reset, export. Data path
  is decoupled from acquisition (downsampled server-side to ≤ 10 Hz for live).
- **Status bar**: camera fps, display fps, received, recording drops (red when > 0), camera gaps
  (amber), REC elapsed, free disk (red below threshold). Never shows green.
- Playback uses the same frame with the transport (play/pause/step/speed/scrub) replacing the
  status bar's left half, and the plot dock showing the whole recording with a cursor.
- Panel collapse state persists in `localStorage`.

## 4. Experiments page

- Header row: count, total size, sort (newest / name / duration), filter (text over name and
  metadata), "open experiments folder" (reveal root).
- Card: thumbnail (4:3), name (mono), duration · frames · case · RF power, completeness badge
  (`complete` green-tinted text on dark; `INCOMPLETE · n dropped` red), actions: **open**
  (primary), **reveal**, **export** (disabled until M7).
- **Thumbnails**: at finalize the recorder renders `preview.png` (frame at 50 %, iron palette,
  auto-scaled to that frame, 320×240) and `keyframes.png` (a horizontal strip of 12 frames at
  0…100 %, each 160×120, same palette; scale fixed to the whole-run min/max so the strip shows
  heating). Hovering the card scrubs through the 12 keyframes by mouse x-position and shows
  `t = … s` and that frame's max. Both files are visualization products, written next to the store,
  listed in `manifest.json.previews`, and regenerable from the data (`fri-thumbs` for old runs).
- Incomplete experiments (no manifest) get a thumbnail generated on demand from the last chunk.

## 5. Reveal in file manager

- `POST /api/experiments/{name}/reveal` → operator runs `open -R <path>` (macOS),
  `explorer /select,<path>` (Windows), `xdg-open <dir>` (Linux). Only paths inside the
  experiments root are allowed (resolved, no symlink escape); only permitted for local origins and
  the configured site origin; returns 501 with a clear message when no desktop is available.
- `POST /api/experiments/reveal-root` opens the experiments root.
- The UI shows the resolved path in mono under the button so it can be copied when reveal is not
  possible (headless acquisition PC).

## 6. Deployment model

### 6.1 Components

| Component | Where | Built from |
|---|---|---|
| **Site** (GitHub Pages) | `https://<org>.github.io/flir-research-interface/` | `frontend/dist` + `site/` landing page, published by CI on tag |
| **Operator** | installed on the acquisition machine, background service on `127.0.0.1:8000` | the Python backend, bundled per platform by CI, embedding the same `frontend/dist` |
| **SDK artifacts** | private artifact location owned by the project (configurable base URL, e.g. a GT storage share or a private release with token) | Spinnaker installers + PySpin wheels per platform, uploaded by the owner; `sdk-manifest.json` lists filename, sha256, platform, python tag |

### 6.2 First-run flow (new machine)

1. User opens the site. It detects OS/CPU and shows **one** primary button: "Install operator".
   The download is the platform installer (`.pkg` arm64 macOS, `.msi` Windows x64, `.deb`/AppImage
   Linux x64/arm64). Secondary: "already installed? open interface".
2. Installer places the operator, registers the service (launchd / Windows service / systemd
   user unit), installs a menu-bar/tray item (status, open interface, check for updates, quit),
   starts the service.
3. The site polls `http://localhost:8000/api/health` every 2 s; when it answers, the page shows
   "operator connected · vX.Y" and continues into the existing Setup page (SDK → discovery →
   connect) rendered by the site UI against the operator API.
4. **SDK step**: the operator's setup endpoint reports what is missing (Spinnaker runtime, PySpin
   wheel for its Python). One button "Install camera SDK" makes the operator download the matching
   artifacts from the SDK artifact base URL (verifying sha256 against `sdk-manifest.json`), run the
   Spinnaker installer (with the OS elevation prompt), and pip-install the PySpin wheel into its own
   environment, then re-check. On macOS the Homebrew prerequisites (`libomp libusb ffmpeg@6`) are
   bundled as static copies inside the operator's runtime where licenses allow, otherwise installed
   via the same step.
5. Network step and connect: unchanged from today.

### 6.3 Connected mode (site UI ↔ local operator)

- Base URL of the operator is `http://localhost:8000` (configurable in the site's settings, stored
  in `localStorage`). `localhost` is a trustworthy origin, so HTTPS→localhost fetch and `ws://`
  are permitted in Chrome, Edge and Firefox.
- **Chrome Local Network Access**: the operator answers preflights with
  `Access-Control-Allow-Private-Network: true`; the browser shows its one-time permission prompt.
- **CORS**: the operator allows exactly two origin classes: `http://localhost:*` /
  `http://127.0.0.1:*` and the configured site origin. All non-GET endpoints require the header
  `X-FRI-Client: 1`, forcing a preflight so other websites cannot issue state-changing requests.
- **Version handshake**: `/api/health` returns `api_version` and `app_version`. The UI refuses
  to operate on an `api_version` major mismatch and offers "update operator" (menu-bar update or
  re-download). Minor mismatch shows a banner.
- **Safari**: blocks `ws://localhost` from HTTPS pages. Detected at runtime (WebSocket error after
  health OK) → the site redirects to `http://localhost:8000` (operator-served identical UI) with a
  one-line explanation.

### 6.4 Offline mode

- The operator serves the identical UI at `http://localhost:8000`; the site shows an "open local
  copy" link whenever the operator is detected. Full functionality without internet.
- The site is a PWA (service worker caches the UI shell and assets, network-first for updates),
  so a machine that has visited once can load the site UI offline; it still needs the operator.
- The SDK step and updates are the only steps that need internet (or the private artifact
  location); the UI says so explicitly.

### 6.5 Updates

- CI builds operator installers and the site on every tagged release. The operator checks the
  release feed daily (opt-out) and the tray item offers "update to vX.Y". Updating never touches
  `experiments/`.

### 6.6 Security posture

- Operator binds to `127.0.0.1` only (LAN exposure is Milestone 10, with a token and mDNS).
- No credentials in URLs. Camera RTSP credentials remain in the operator's local `.env`/keychain.
- The public repository and the public site never contain FLIR SDK binaries; the artifact base
  URL is configuration, defaulting to empty (the SDK step then shows the manual Teledyne path).

### 6.7 What stays manual, by design

- Approving the OS elevation prompt for the Spinnaker installer.
- Clicking Chrome's local-network permission prompt once.
- Setting the camera-facing adapter's IP when the camera is on a different subnet (the UI shows
  the exact command; changing host network settings automatically is out of scope by the brief).

## 7. Data flow changes required

- `GET /api/health` gains `api_version`, `app_version`, `platform`, `experiments_root`.
- New: `POST /api/setup/sdk/install` (async job with progress), `GET /api/setup/sdk/job/{id}`.
- New: `POST /api/experiments/{name}/reveal`, `POST /api/experiments/reveal-root`.
- New: `GET /api/experiments/{name}/preview.png`, `GET /api/experiments/{name}/keyframes.png`.
- Recorder finalize renders previews; `manifest.json.previews` lists them with sha256.
- Frontend gains a runtime "operator base URL" and an `apiFetch` wrapper that adds `X-FRI-Client`.
- Frontend theme tokens file and component restyle; Studio layout components: `ToolStrip`,
  `Rail` (+ `RailSection`), `PlotDock` (placeholder until M6), `StatusBar`.

## 8. Error handling

- Operator unreachable: site shows the install/waiting state with the last error and the port it
  is trying; never a blank page.
- WebSocket blocked (Safari) or repeatedly failing: automatic switch to operator-served UI.
- SDK install failure: full log shown inline, with the manual steps as fallback.
- Reveal unavailable: 501 + path shown for copy.
- Preview generation failure never fails finalization; the card shows a neutral placeholder and
  a "regenerate" action.

## 9. Testing

- Unit (Python): CORS/origin rules, `X-FRI-Client` enforcement, path containment for reveal,
  preview rendering (deterministic on a synthetic experiment), sdk-manifest verification (sha256,
  platform match), version handshake logic.
- Unit (TS, node --test): theme token presence, layout state persistence reducer, operator base
  URL resolution, version-compat decision, keyframe scrub index math.
- Browser verification (manual/automated with the preview tool): Studio layout at 1280×800 and
  1920×1080, collapse states, Experiments grid with hover scrub, reveal on macOS, site→operator
  handshake with the site served from a local static server on another origin (simulates Pages).
- CI: matrix build of operator installers (macOS arm64, Windows x64, Linux x64/arm64), smoke-run
  `fri-serve --check` in each artifact, publish site on tag.

## 10. Sequencing

1. Theme tokens + Studio layout shell + restyled existing panels (no new features).
2. Experiments card grid + previews/keyframes + reveal.
3. Operator API hardening for cross-origin use (CORS, header, health/version).
4. Site landing page + operator detection + PWA; CI for site.
5. Operator packaging per platform + SDK install job from the private artifact location.
6. Camera-controls rail section (case, object params, NUC, frame rate) with recording lock.

Items 1–2 are UI work on the current milestones; 3–5 are the deployment epic (Milestone 10
brought forward); 6 closes the outstanding Milestone-4 item.
