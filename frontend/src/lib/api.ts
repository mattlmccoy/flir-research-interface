import { apiUrl, loadOperatorBase, saveOperatorBase } from "./operator.ts";

/** Site mode: the UI is served from GitHub Pages and talks to a local operator (spec §6.3). */
export const SITE_MODE = import.meta.env.VITE_SITE_MODE === "1";
const storage = (() => { try { return typeof localStorage !== "undefined" ? localStorage : null; } catch { return null; } })();
let BASE = loadOperatorBase(storage, { siteMode: SITE_MODE });
export function operatorBase(): string { return BASE; }
export function setOperatorBase(base: string): void { saveOperatorBase(storage, base); BASE = loadOperatorBase(storage, { siteMode: SITE_MODE }); }
const u = (path: string) => apiUrl(BASE, path);

/** fetch against the operator; cross-origin writes carry X-FRI-Client so the operator's preflight guard passes. */
function req(path: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers ?? {});
  if (method !== "GET" && method !== "HEAD") headers.set("X-FRI-Client", "1");
  return fetch(u(path), { ...init, headers });
}

export interface Device { backend: string; model: string; serial: string; ip_address: string | null; mac_address: string | null; firmware: string | null; interface: string; }
export interface Status { state: string; backend?: string | null; device?: Device | null; frames_received?: number; viz_dropped?: number; camera_fps?: number | null; last_error?: string | null; }

async function j<T>(r: Promise<Response>): Promise<T> {
  const res = await r;
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try {
      const parsed: unknown = JSON.parse(text);
      if (parsed && typeof parsed === "object" && typeof (parsed as { detail?: unknown }).detail === "string") {
        detail = (parsed as { detail: string }).detail;
      }
    } catch {
      // not JSON: fall back to the raw text
    }
    throw new Error(`${res.status} ${detail}`);
  }
  return (await res.json()) as T;
}
export interface VisibleStatus { state: string; restarts?: number; file?: string | null; started_host_ns?: number | null; url?: string; error?: string | null; reason?: string; }
export interface ArmedStatus { trigger: Record<string, unknown>; machine: { state: string; frames_recorded: number; reason: string | null; sustain: number }; watched_value: number | null; watched_roi: number | null; ring_frames: number; pretrigger_frames: number; }
export interface RecordingStatus { state: string; armed?: ArmedStatus; visible?: VisibleStatus; experiment_dir?: string | null; frames_received?: number; frames_written?: number; queue_depth?: number; queue_dropped?: number; frame_id_gaps?: number; repeated_frames?: number; every_nth?: number; frames_skipped_interval?: number; duration_s?: number; recorded_fps?: number | null; free_space_gb?: number | null; min_free_gb?: number; error?: string | null; experiments_root?: string; }
export interface Previews {
  units: "celsius" | "counts";
  preview: { file: string; frame_index: number; t_s: number; size?: [number, number]; units?: string; sha256: string };
  keyframes: { file: string; count: number; indices: number[]; t_s: number[]; tile?: [number, number]; vmin: number; vmax: number; units?: string; sha256: string };
}
export interface RevealResult { ok: boolean; path: string; error?: string; }
export interface Health { status: string; version: string; app_version?: string; api_version?: string; platform?: string; }
export interface ProfileSuggestion { matches: { id: string; title: string; hits: string[] }[]; fields: (ProfileField & { why: string; source: string })[]; marks: { label: string; key?: string; source: string }[]; }
export interface ProfileField { key: string; label: string; type: "text" | "number"; }
export interface Profile { name: string; fields: ProfileField[]; marks: { label: string; key?: string }[]; }
export const DEFAULT_PROFILE: Profile = { name: "default", fields: [{ key: "operator", label: "Operator", type: "text" }, { key: "sample_id", label: "Sample ID", type: "text" }, { key: "notes", label: "Notes", type: "text" }], marks: [{ label: "event A", key: "a" }, { label: "event B", key: "b" }] };
export interface Hdf5Export { path: string; size_bytes: number; sha256: string; n_frames: number; }
export interface ThermalVideoExport { path: string; frames: number; fps: number; width: number; height: number; vmin: number; vmax: number; units: string; bytes: number; }
/** Progress of an on-demand derived regenerate (background job). */
export interface DerivedJob { state: "running" | "done" | "error" | "idle"; step?: string; done?: number; total?: number; exports?: { name: string; bytes: number }[] | null; error?: string | null; }
/** Options for a media-export render (a window of frames to MP4/GIF with overlays). */
export interface MediaOptions { start: number; stop: number; step?: number; scale?: number; speed?: number; fps?: number | null; fmt: "mp4" | "gif"; with_rois?: boolean; frame_stats?: boolean; timestamp?: boolean; colorbar?: boolean; title?: string | null; plot_roi?: number | null; plot_rois?: number[]; plot_stat?: string; plot_stats?: string[]; plot_series?: string[]; overlay_rois?: number[]; visible_opacity?: number; palette?: string; rois?: unknown[] | null; }
/** Progress of a media-export render (background job). */
export interface MediaJob { state: "running" | "done" | "error" | "idle"; step?: string; done?: number; total?: number; file?: { name: string; bytes: number; note?: string | null } | null; error?: string | null; }
export interface RangeJob { state: "running" | "done" | "error" | "idle"; done: number; total: number; error?: string | null; }
/** A user-selectable external drive for offload. */
export interface Volume { label: string; mount: string; fstype: string; total_bytes: number; free_bytes: number; is_registered?: boolean; }
/** Storage state: the local root and the registered drive (if any). */
export interface StorageInfo {
  local: { root: string; free_bytes: number; total_bytes: number };
  drive: { mount: string; root: string; connected: boolean; free_bytes?: number; total_bytes?: number } | null;
}
/** Progress of an offload/restore move (background job). */
export interface MoveJob { state: "running" | "done" | "error" | "idle"; to?: "drive" | "local"; done?: number; total?: number; error?: string | null; }

export interface Experiment {
  name: string;
  path: string;
  size_bytes?: number;
  complete: boolean;
  frames_on_disk: number;
  has_metadata?: boolean;
  manifest: Record<string, unknown> | null;
  metadata: Record<string, unknown> | null;
  previews?: Previews | null;
  ir_format?: string | null;
  duration_s?: number;
  n_frames?: number;
  experiment?: Record<string, unknown> | null;
  error?: string;
  started_utc?: string | null;
  /** ROIs stored with the recording (what its derived files were built from). */
  rois?: Record<string, unknown>[] | null;
  /** Which storage the run lives in, and its root (from the union list). */
  library?: "local" | "drive";
  root?: string;
}

export interface ExperimentInfo { name: string; path: string; n_frames: number; size_bytes?: number; width: number; height: number; duration_s: number; complete: boolean; ir_format: string | null; conversion: Record<string, unknown> | null; experiment: Record<string, unknown> | null; camera: Record<string, unknown> | null; software: Record<string, unknown> | null; started_utc: string | null; events?: Record<string, unknown>[]; manifest: Record<string, unknown> | null; visible?: { file?: string | null; measured_fps?: number | null; error?: string | null } | null; visible_alignment?: Record<string, unknown> | null; rois?: Record<string, unknown>[] | null; thermal_preview?: { path: string; bytes: number } | null; exports?: { name: string; bytes: number }[]; }
export interface Timeline { t_s: number[]; frame_id: number[]; }
export interface ExperimentEvent { t_s?: number; type?: string; name?: string; [k: string]: unknown; }
export interface RoiSeries {
  units: "celsius" | "counts";
  t_s: number[];
  frame_id: number[];
  series: Record<string, { value?: (number | null)[]; min?: (number | null)[]; max?: (number | null)[]; mean?: (number | null)[] }>;
  events: ExperimentEvent[];
}

export const api = {
  experiment: (name: string) => j<ExperimentInfo>(req(`/api/experiments/${encodeURIComponent(name)}`)),
  timeline: (name: string) => j<Timeline>(req(`/api/experiments/${encodeURIComponent(name)}/timeline`)),
  series: (name: string, rois: unknown[], valid?: { min: number; max: number } | null, maxPoints = 0) =>
    j<RoiSeries>(req(`/api/experiments/${encodeURIComponent(name)}/series?rois=${encodeURIComponent(JSON.stringify(rois))}${valid ? `&valid=${valid.min},${valid.max}` : ""}${maxPoints ? `&max_points=${maxPoints}` : ""}`)),
  seriesCsvUrl: (name: string, rois: unknown[]) =>
    u(`/api/experiments/${encodeURIComponent(name)}/export/series.csv?rois=${encodeURIComponent(JSON.stringify(rois))}`),
  frameExportUrl: (name: string, index: number, format: "csv" | "tiff" | "png" | "npy") =>
    u(`/api/experiments/${encodeURIComponent(name)}/frames/${index}/export?format=${format}`),
  exportHdf5: (name: string) =>
    j<Hdf5Export>(req(`/api/experiments/${encodeURIComponent(name)}/export/hdf5`, { method: "POST" })),
  exportFrames: (name: string, start: number, stop: number, step: number, format: string) =>
    j<{ path: string; frames: number[]; n: number; format: string; size_bytes: number }>(req(`/api/experiments/${encodeURIComponent(name)}/export/frames`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ start, stop, step, format }) })),
  exportReport: (name: string) => j<{ path: string; pages: number; size_bytes: number }>(req(`/api/experiments/${encodeURIComponent(name)}/export/report`, { method: "POST" })),
  reportUrl: (name: string) => u(`/api/experiments/${encodeURIComponent(name)}/report.pdf`),
  exportThermalVideo: (name: string) =>
    j<ThermalVideoExport>(req(`/api/experiments/${encodeURIComponent(name)}/export/thermal-video`, { method: "POST" })),
  /** Persist the ROIs currently on screen into the recording so derived files can match them. */
  putRois: (name: string, rois: unknown[]) =>
    j<{ rois: number }>(req(`/api/experiments/${encodeURIComponent(name)}/rois`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ rois }) })),
  /** Start a background regenerate of the ROI-dependent derived files; poll exportDerivedStatus.
   * `video=false` is the quick option (plot + CSV + images only, skips the slow video encode). */
  exportDerived: (name: string, video = true) =>
    j<DerivedJob>(req(`/api/experiments/${encodeURIComponent(name)}/export/derived${video ? "" : "?video=false"}`, { method: "POST" })),
  exportDerivedStatus: (name: string) =>
    j<DerivedJob>(req(`/api/experiments/${encodeURIComponent(name)}/export/derived/status`)),
  /** Start a media-export render (windowed MP4/GIF with overlays); poll mediaStatus. */
  exportMedia: (name: string, opts: MediaOptions) =>
    j<MediaJob>(req(`/api/experiments/${encodeURIComponent(name)}/export/media`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(opts) })),
  mediaStatus: (name: string) =>
    j<MediaJob>(req(`/api/experiments/${encodeURIComponent(name)}/export/media/status`)),
  /** Precompute the display temperature range (the slow whole-run scan) as a job with progress. */
  computeRange: (name: string) =>
    j<RangeJob>(req(`/api/experiments/${encodeURIComponent(name)}/range/compute`, { method: "POST" })),
  rangeStatus: (name: string) =>
    j<RangeJob>(req(`/api/experiments/${encodeURIComponent(name)}/range/status`)),
  clipUrl: (name: string, file: string) =>
    u(`/api/experiments/${encodeURIComponent(name)}/exports/clips/${encodeURIComponent(file)}`),
  /** A composed preview frame (PNG) for the editor: same overlays as the export, at `index`. */
  mediaPreviewUrl: (name: string, index: number, o: { with_rois?: boolean; frame_stats?: boolean; timestamp?: boolean; colorbar?: boolean; title?: string | null; plot_series?: string[]; overlay_rois?: number[]; visible_opacity?: number; palette?: string; start?: number; stop?: number }) =>
    u(`/api/experiments/${encodeURIComponent(name)}/export/media/preview?index=${index}&scale=1&with_rois=${o.with_rois !== false}&frame_stats=${!!o.frame_stats}&timestamp=${o.timestamp !== false}&colorbar=${o.colorbar !== false}${o.palette ? `&palette=${o.palette}` : ""}${o.title ? `&title=${encodeURIComponent(o.title)}` : ""}${(o.plot_series ?? []).map((s) => `&plot_series=${encodeURIComponent(s)}`).join("")}${(o.overlay_rois ?? []).map((r) => `&overlay_rois=${r}`).join("")}${o.visible_opacity ? `&visible_opacity=${o.visible_opacity}` : ""}${o.plot_series?.length ? `&start=${o.start ?? 0}&stop=${o.stop ?? 0}` : ""}`),
  exportFileUrl: (name: string, file: string) => u(`/api/experiments/${encodeURIComponent(name)}/exports/${encodeURIComponent(file)}`),
  thermalVideoUrl: (name: string) => u(`/api/experiments/${encodeURIComponent(name)}/thermal_preview.mp4`),
  frameBuffer: async (name: string, index: number): Promise<ArrayBuffer> => {
    const res = await req(`/api/experiments/${encodeURIComponent(name)}/frames/${index}`);
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    return res.arrayBuffer();
  },
  frameBlock: async (name: string, start: number, count: number): Promise<ArrayBuffer> => {
    const res = await req(`/api/experiments/${encodeURIComponent(name)}/frames?start=${start}&count=${count}`);
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    return res.arrayBuffer();
  },
  recordingStart: (name: string, metadata: Record<string, unknown>, visible = false, rois: unknown[] | null = null, nucHold = true, everyNth = 1) =>
    j<{ state: string; experiment_dir: string; visible?: VisibleStatus }>(req("/api/recording/start", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name, metadata, visible, rois, nuc_hold: nucHold, every_nth: everyNth }) })),
  recordingStop: () => j<Record<string, unknown>>(req("/api/recording/stop", { method: "POST" })),
  recordingArm: (name: string, metadata: Record<string, unknown>, visible: boolean, rois: unknown[] | null, trigger: unknown, nucHold = true) =>
    j<{ state: string }>(req("/api/recording/arm", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name, metadata, visible, rois, trigger, nuc_hold: nucHold }) })),
  recordingDisarm: () => j<Record<string, unknown>>(req("/api/recording/disarm", { method: "POST" })),
  recordingArmStart: () => j<Record<string, unknown>>(req("/api/recording/arm/start", { method: "POST" })),
  recordingStatus: () => j<RecordingStatus>(req("/api/recording/status")),
  recordingEvent: (name: string, note?: string) =>
    j<ExperimentEvent>(req("/api/recording/event", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name, note: note || null }) })),
  patchMetadata: (name: string, experiment: Record<string, unknown>) =>
    j<{ experiment: Record<string, unknown> }>(req(`/api/experiments/${encodeURIComponent(name)}/metadata`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ experiment }) })),
  experiments: () => j<Experiment[]>(req("/api/experiments")),
  previewUrl: (name: string) => u(`/api/experiments/${encodeURIComponent(name)}/preview.png`),
  visibleVideoUrl: (name: string) => u(`/api/experiments/${encodeURIComponent(name)}/visible.mp4`),
  visibleLiveUrl: () => u("/api/visible/live.mjpeg"),
  getAlignment: () => j<Record<string, unknown>>(req("/api/calibration/visible")),
  putAlignment: (doc: Record<string, unknown>) =>
    j<Record<string, unknown>>(req("/api/calibration/visible", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(doc) })),
  keyframesUrl: (name: string) => u(`/api/experiments/${encodeURIComponent(name)}/keyframes.png`),
  regeneratePreviews: (name: string) => j<Previews>(req(`/api/experiments/${encodeURIComponent(name)}/previews`, { method: "POST" })),
  reveal: (name: string) => j<RevealResult>(req(`/api/experiments/${encodeURIComponent(name)}/reveal`, { method: "POST" })),
  experimentsSummary: () => j<{ count: number; size_bytes: number; free_space_gb: number }>(req("/api/experiments/summary")),
  profile: () => j<Profile>(req("/api/profile")),
  profileSuggest: (q: string) => j<ProfileSuggestion>(req(`/api/profile/suggest?q=${encodeURIComponent(q)}`)),
  saveProfile: (p: Profile) => j<Profile>(req("/api/profile", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(p) })),
  deleteExperiment: (name: string) =>
    j<{ deleted: string }>(req(`/api/experiments/${encodeURIComponent(name)}`, { method: "DELETE" })),
  // -- external-drive storage (offload) --
  storage: () => j<StorageInfo>(req("/api/storage")),
  storageVolumes: () => j<Volume[]>(req("/api/storage/volumes")),
  registerDrive: (mount: string) =>
    j<StorageInfo>(req("/api/storage/drive", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ mount }) })),
  forgetDrive: () => j<StorageInfo>(req("/api/storage/drive", { method: "DELETE" })),
  moveExperiment: (name: string, to: "drive" | "local") =>
    j<MoveJob>(req(`/api/experiments/${encodeURIComponent(name)}/move`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ to }) })),
  moveStatus: (name: string) =>
    j<MoveJob>(req(`/api/experiments/${encodeURIComponent(name)}/move/status`)),
  revealRoot: () => j<RevealResult>(req("/api/experiments/reveal-root", { method: "POST" })),
  health: () => j<Health>(req("/api/health")),
  sdk: () => j<Record<string, unknown>>(req("/api/setup/sdk")),
  discovery: () => j<Record<string, unknown>>(req("/api/setup/discovery")),
  forceIp: (mac: string, ip: string, subnet_mask: string, gateway = "0.0.0.0") =>
    j<{ acked: boolean; camera_ip: string | null; reachable_by_sdk: boolean }>(req("/api/setup/force-ip", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ mac, ip, subnet_mask, gateway }) })),
  devices: (backend: string) => j<Device[]>(req(`/api/camera/devices?backend=${encodeURIComponent(backend)}`)),
  status: () => j<Status>(req("/api/camera/status")),
  info: () => j<Record<string, unknown>>(req("/api/camera/info")),
  setParameters: (values: Record<string, unknown>) =>
    j<{ applied: Record<string, unknown> }>(req("/api/camera/parameters", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ values }) })),
  nuc: () => j<{ ok: boolean }>(req("/api/camera/nuc", { method: "POST" })),
  connect: (backend: string, serial?: string) =>
    j<{ state: string }>(req("/api/camera/connect", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ backend, serial }) })),
  disconnect: () => j<{ state: string }>(req("/api/camera/disconnect", { method: "POST" })),
};
