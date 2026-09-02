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
export interface RecordingStatus { state: string; experiment_dir?: string | null; frames_received?: number; frames_written?: number; queue_depth?: number; queue_dropped?: number; frame_id_gaps?: number; duration_s?: number; recorded_fps?: number | null; free_space_gb?: number | null; min_free_gb?: number; error?: string | null; experiments_root?: string; }
export interface Previews {
  units: "celsius" | "counts";
  preview: { file: string; frame_index: number; t_s: number; size?: [number, number]; units?: string; sha256: string };
  keyframes: { file: string; count: number; indices: number[]; t_s: number[]; tile?: [number, number]; vmin: number; vmax: number; units?: string; sha256: string };
}
export interface RevealResult { ok: boolean; path: string; error?: string; }
export interface Hdf5Export { path: string; size_bytes: number; sha256: string; n_frames: number; }

export interface Experiment {
  name: string;
  path: string;
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
}

export interface ExperimentInfo { name: string; path: string; n_frames: number; width: number; height: number; duration_s: number; complete: boolean; ir_format: string | null; conversion: Record<string, unknown> | null; experiment: Record<string, unknown> | null; camera: Record<string, unknown> | null; software: Record<string, unknown> | null; started_utc: string | null; events?: Record<string, unknown>[]; manifest: Record<string, unknown> | null; }
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
  experiment: (name: string) => j<ExperimentInfo>(fetch(`/api/experiments/${encodeURIComponent(name)}`)),
  timeline: (name: string) => j<Timeline>(fetch(`/api/experiments/${encodeURIComponent(name)}/timeline`)),
  series: (name: string, rois: unknown[]) =>
    j<RoiSeries>(fetch(`/api/experiments/${encodeURIComponent(name)}/series?rois=${encodeURIComponent(JSON.stringify(rois))}`)),
  seriesCsvUrl: (name: string, rois: unknown[]) =>
    `/api/experiments/${encodeURIComponent(name)}/export/series.csv?rois=${encodeURIComponent(JSON.stringify(rois))}`,
  frameExportUrl: (name: string, index: number, format: "csv" | "tiff" | "png" | "npy") =>
    `/api/experiments/${encodeURIComponent(name)}/frames/${index}/export?format=${format}`,
  exportHdf5: (name: string) =>
    j<Hdf5Export>(fetch(`/api/experiments/${encodeURIComponent(name)}/export/hdf5`, { method: "POST" })),
  frameBuffer: async (name: string, index: number): Promise<ArrayBuffer> => {
    const res = await fetch(`/api/experiments/${encodeURIComponent(name)}/frames/${index}`);
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    return res.arrayBuffer();
  },
  recordingStart: (name: string, metadata: Record<string, unknown>) =>
    j<{ state: string; experiment_dir: string }>(fetch("/api/recording/start", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name, metadata }) })),
  recordingStop: () => j<Record<string, unknown>>(fetch("/api/recording/stop", { method: "POST" })),
  recordingStatus: () => j<RecordingStatus>(fetch("/api/recording/status")),
  recordingEvent: (name: string, note?: string) =>
    j<ExperimentEvent>(fetch("/api/recording/event", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name, note: note || null }) })),
  patchMetadata: (name: string, experiment: Record<string, unknown>) =>
    j<{ experiment: Record<string, unknown> }>(fetch(`/api/experiments/${encodeURIComponent(name)}/metadata`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ experiment }) })),
  experiments: () => j<Experiment[]>(fetch("/api/experiments")),
  previewUrl: (name: string) => `/api/experiments/${encodeURIComponent(name)}/preview.png`,
  keyframesUrl: (name: string) => `/api/experiments/${encodeURIComponent(name)}/keyframes.png`,
  regeneratePreviews: (name: string) => j<Previews>(fetch(`/api/experiments/${encodeURIComponent(name)}/previews`, { method: "POST" })),
  reveal: (name: string) => j<RevealResult>(fetch(`/api/experiments/${encodeURIComponent(name)}/reveal`, { method: "POST" })),
  revealRoot: () => j<RevealResult>(fetch("/api/experiments/reveal-root", { method: "POST" })),
  health: () => j<{ status: string; version: string }>(fetch("/api/health")),
  sdk: () => j<Record<string, unknown>>(fetch("/api/setup/sdk")),
  discovery: () => j<Record<string, unknown>>(fetch("/api/setup/discovery")),
  devices: (backend: string) => j<Device[]>(fetch(`/api/camera/devices?backend=${encodeURIComponent(backend)}`)),
  status: () => j<Status>(fetch("/api/camera/status")),
  info: () => j<Record<string, unknown>>(fetch("/api/camera/info")),
  setParameters: (values: Record<string, unknown>) =>
    j<{ applied: Record<string, unknown> }>(fetch("/api/camera/parameters", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ values }) })),
  nuc: () => j<{ ok: boolean }>(fetch("/api/camera/nuc", { method: "POST" })),
  connect: (backend: string, serial?: string) =>
    j<{ state: string }>(fetch("/api/camera/connect", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ backend, serial }) })),
  disconnect: () => j<{ state: string }>(fetch("/api/camera/disconnect", { method: "POST" })),
};
