export interface Device { backend: string; model: string; serial: string; ip_address: string | null; mac_address: string | null; firmware: string | null; interface: string; }
export interface Status { state: string; backend?: string | null; device?: Device | null; frames_received?: number; viz_dropped?: number; camera_fps?: number | null; last_error?: string | null; }

async function j<T>(r: Promise<Response>): Promise<T> {
  const res = await r;
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return (await res.json()) as T;
}
export interface RecordingStatus { state: string; experiment_dir?: string | null; frames_received?: number; frames_written?: number; queue_depth?: number; queue_dropped?: number; frame_id_gaps?: number; duration_s?: number; recorded_fps?: number | null; free_space_gb?: number | null; error?: string | null; experiments_root?: string; }
export interface Experiment { name: string; path: string; complete: boolean; frames_on_disk: number; has_metadata: boolean; manifest: Record<string, unknown> | null; metadata: Record<string, unknown> | null; }

export const api = {
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
