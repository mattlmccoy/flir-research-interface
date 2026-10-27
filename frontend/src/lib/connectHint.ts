// Plain-language camera connect error. The operator diagnoses a failed connect or a dropped
// stream (Spinnaker -1023 subnet overlap, -1024 adapter removed) and reports it in
// /api/camera/status as last_error_hint {kind, message, command} next to the raw last_error.
// This picks what the UI shows: the message, the copyable fix command, and the raw error.

/** The operator's hint object (backend net_diagnostics.explain_camera_error). */
export interface ErrorHint { kind: string; message: string; command: string | null; }

export interface HintFields { state: string; last_error?: string | null; last_error_hint?: ErrorHint | null; }

export interface ConnectHint { level: "err" | "warn"; short: string; message: string; command: string | null; raw: string | null; }

const SHORT: Record<string, string> = {
  subnet_conflict: "subnet conflict",
  subnet_conflict_unlocated: "subnet conflict",
  adapter_removed: "adapter gone",
  adapter_missing: "adapter gone",
};

export function connectHint(s: HintFields): ConnectHint | null {
  const h = s.last_error_hint;
  if (!h || typeof h.message !== "string" || !h.message) return null;
  return {
    level: s.state === "reconnecting" ? "warn" : "err",
    short: SHORT[h.kind] ?? "camera problem",
    message: h.message,
    command: typeof h.command === "string" && h.command ? h.command : null,
    raw: s.last_error ?? null,
  };
}
