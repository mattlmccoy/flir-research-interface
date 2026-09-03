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
export const INSTALL_PS1 = "https://raw.githubusercontent.com/mattlmccoy/flir-research-interface/main/install.ps1";
export const TELEDYNE_SDK = "https://www.teledynevisionsolutions.com/products/spinnaker-sdk/";
export interface InstallSteps { command: string | null; shell: string; steps: string[]; }

/** What the first-run page shows: a one-line installer per platform. */
export function installSteps(platform: Platform): InstallSteps {
  const tail = [
    "The FLIR Spinnaker SDK is fetched from this project's internal mirror; if that fails the script says so, you get it from Teledyne's page (link below) and re-run the same command.",
    "Leave this page open: it detects the operator by itself and continues.",
  ];
  if (platform === "windows") {
    return {
      command: `irm ${INSTALL_PS1} | iex`,
      shell: "PowerShell (Start → type PowerShell)",
      steps: [
        "Paste the command into PowerShell and press Enter. It installs git, Python 3.12, uv and ffmpeg with winget, downloads this project into your home folder, installs the Spinnaker SDK silently, asks for the camera IP and RTSP password, and registers a logon task that runs the operator.",
        ...tail,
      ],
    };
  }
  if (platform === "linux") {
    return {
      command: `curl -fsSL ${INSTALL_SH} | bash`,
      shell: "a terminal (Ubuntu 20.04 / 22.04 / 24.04, amd64 or arm64)",
      steps: [
        "Paste the command and press Enter. It installs git, ffmpeg and uv, downloads this project into your home folder, installs the Spinnaker packages and PySpin, asks for the camera IP and RTSP password, and enables a systemd user service that runs the operator.",
        ...tail,
      ],
    };
  }
  return {
    command: `curl -fsSL ${INSTALL_SH} | bash`,
    shell: "Terminal (⌘-space, type Terminal)",
    steps: [
      "Paste the command and press Return. It installs the tools with Homebrew, downloads this project into ~/flir-research-interface, installs the Spinnaker SDK (asks for your Mac password once), asks for the camera IP and RTSP password, and starts the operator as a login item.",
      ...tail,
    ],
  };
}

export interface RestartHints { where: string; restart: string; manual: string; log: string; }

/** For a machine that already has the operator installed but where nothing answers. */
export function restartHints(platform: Platform): RestartHints {
  const manual = "cd ~/flir-research-interface/backend && uv run fri-serve --port 8000";
  if (platform === "windows") {
    return {
      where: "installed as a logon task named \"FLIR Research Interface operator\" (Task Scheduler)",
      restart: "Start-ScheduledTask -TaskName \"FLIR Research Interface operator\"",
      manual: "cd $HOME\\flir-research-interface\\backend; uv run fri-serve --port 8000",
      log: "the PowerShell window that runs fri-serve (task output), or run it by hand to see it",
    };
  }
  if (platform === "linux") {
    return {
      where: "installed as a systemd user service (fri-operator.service), starts at login",
      restart: "systemctl --user restart fri-operator.service",
      manual,
      log: "journalctl --user -u fri-operator.service -f",
    };
  }
  return {
    where: "installed as a login item (launchd LaunchAgent io.github.mattlmccoy.flir-research-interface); it starts at login and restarts itself if it dies",
    restart: "launchctl kickstart -k gui/$(id -u)/io.github.mattlmccoy.flir-research-interface",
    manual,
    log: "~/flir-research-interface/backend/operator.log",
  };
}
