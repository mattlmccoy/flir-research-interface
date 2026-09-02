export interface Device { backend: string; model: string; serial: string; ip_address: string | null; mac_address: string | null; firmware: string | null; interface: string; }
export interface Status { state: string; backend?: string | null; device?: Device | null; frames_received?: number; viz_dropped?: number; camera_fps?: number | null; last_error?: string | null; }

async function j<T>(r: Promise<Response>): Promise<T> {
  const res = await r;
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return (await res.json()) as T;
}
export interface RecordingStatus { state: string; experiment_dir?: string | null; frames_received?: number; frames_written?: number; queue_depth?: number; queue_dropped?: number; frame_id_gaps?: number; duration_s?: number; recorded_fps?: number | null; free_space_gb?: number | null; min_free_gb?: number; error?: string | null; experiments_root?: string; }
export interface Experiment { name: string; path: string; complete: boolean; frames_on_disk: number; has_metadata: boolean; manifest: Record<string, unknown> | null; metadata: Record<string, unknown> | null; }

export interface ExperimentInfo { name: string; path: string; n_frames: number; width: number; height: number; duration_s: number; complete: boolean; ir_format: string | null; conversion: Record<string, unknown> | null; experiment: Record<string, unknown> | null; camera: Record<string, unknown> | null; software: Record<string, unknown> | null; started_utc: string | null; events?: Record<string, unknown>[]; manifest: Record<string, unknown> | null; }
export interface Timeline { t_s: number[]; frame_id: number[]; }

export const api = {
  experiment: (name: string) => j<ExperimentInfo>(fetch(`/api/experiments/${encodeURIComponent(name)}`)),
  timeline: (name: string) => j<Timeline>(fetch(`/api/experiments/${encodeURIComponent(name)}/timeline`)),
  frameBuffer: async (name: string, index: number): Promise<ArrayBuffer> => {
    const res = await fetch(`/api/experiments/${encodeURIComponent(name)}/frames/${index}`);
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    return res.arrayBuffer();
  },
  recordingStart: (name: string, metadata: Record<string, unknown>) =>
    j<{ state: string; experiment_dir: string }>(fetch("/api/recording/start", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name, metadata }) })),
  recordingStop: () => j<Record<string, unknown>>(fetch("/api/recording/stop", { method: "POST" })),
  recordingStatus: () => j<RecordingStatus>(fetch("/api/recording/status")),
  experiments: () => j<Experiment[]>(fetch("/api/experiments")),
  health: () => j<{ status: string; version: string }>(fetch("/api/health")),
  sdk: () => j<Record<string, unknown>>(fetch("/api/setup/sdk")),
  discovery: () => j<Record<string, unknown>>(fetch("/api/setup/discovery")),
  devices: (backend: string) => j<Device[]>(fetch(`/api/camera/devices?backend=${encodeURIComponent(backend)}`)),
  status: () => j<Status>(fetch("/api/camera/status")),
  info: () => j<Record<string, unknown>>(fetch("/api/camera/info")),
  connect: (backend: string, serial?: string) =>
    j<{ state: string }>(fetch("/api/camera/connect", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ backend, serial }) })),
  disconnect: () => j<{ state: string }>(fetch("/api/camera/disconnect", { method: "POST" })),
};
