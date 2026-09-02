/** Platform detection for the first-run page (spec §6.2): one primary install button. */

export type Platform = "macos" | "windows" | "linux" | "unknown";

export function detectPlatform(userAgent: string, platform: string): Platform {
  const ua = `${userAgent} ${platform}`.toLowerCase();
  if (/mac os|macintosh|macintel|macarm/.test(ua)) return "macos";
  if (/windows|win32|win64/.test(ua)) return "windows";
  if (/linux|x11/.test(ua)) return "linux";
  return "unknown";
}

export interface Installer { label: string; note: string; url: string | null; }

const RELEASES = "https://github.com/mattlmccoy/flir-research-interface/releases/latest";

/** Installer entry per platform; `url` is null until CI publishes packaged operators (spec §6.5). */
export function installerFor(p: Platform): Installer {
  switch (p) {
    case "macos":
      return { label: "macOS (Apple silicon .pkg)", url: RELEASES, note: "Installs the operator as a launchd service on 127.0.0.1:8000 with a menu-bar item. Spinnaker + PySpin are installed in the setup step that follows." };
    case "windows":
      return { label: "Windows x64 (.msi)", url: RELEASES, note: "Installs the operator as a Windows service on 127.0.0.1:8000 with a tray icon. Spinnaker + PySpin are installed in the setup step that follows." };
    case "linux":
      return { label: "Linux x64 (.deb / AppImage)", url: RELEASES, note: "Installs the operator as a systemd user unit on 127.0.0.1:8000. Spinnaker + PySpin are installed in the setup step that follows." };
    default:
      return { label: "choose your platform", url: RELEASES, note: "Pick the operator package for your machine from the releases page." };
  }
}


export const INSTALL_SH = "https://raw.githubusercontent.com/mattlmccoy/flir-research-interface/main/install.sh";
export interface InstallSteps { command: string | null; steps: string[]; }

/** What the first-run page shows: a one-line installer on macOS, the manual route elsewhere. */
export function installSteps(platform: Platform): InstallSteps {
  if (platform === "macos") {
    return {
      command: `curl -fsSL ${INSTALL_SH} | bash`,
      steps: [
        "Open Terminal (⌘-space, type Terminal), paste the command, press Return.",
        "It installs the tools with Homebrew, downloads this project into ~/flir-research-interface, asks for the camera IP and RTSP password, and starts the operator as a login item.",
        "The one thing it cannot fetch for you is FLIR's Spinnaker SDK (behind a free Teledyne login). If it is missing the script prints the exact download; install the .pkg and run the command again.",
        "Leave this page open: it detects the operator by itself and continues.",
      ],
    };
  }
  return {
    command: null,
    steps: [
      "Install Python 3.12, uv, ffmpeg 6 and FLIR's Spinnaker SDK + PySpin (see docs/installation.md).",
      "git clone https://github.com/mattlmccoy/flir-research-interface && cd flir-research-interface/backend && uv sync --inexact",
      "Put FRI_CAMERA_HOST, FRI_RTSP_USER, FRI_RTSP_PASSWORD in backend/.env, then: uv run fri-serve --port 8000",
      "Leave this page open: it detects the operator by itself and continues.",
    ],
  };
}
