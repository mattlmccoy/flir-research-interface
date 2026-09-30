// Live "camera stream stalled" warning for an open recording. The recorder reports how long ago
// the last thermal frame arrived (last_frame_age_s), whether that exceeds its stall threshold
// (stream_stalled), and how many stalls it has already listed for this run (stream_stalls). A
// stalled stream leaves the recording open but capturing nothing, and the finished run is marked
// not complete, so the operator must see it while it is happening.

export interface StallFields {
  state: string;
  last_frame_age_s?: number | null;
  stream_stalled?: boolean;
  stream_stalls?: number;
  stall_threshold_s?: number;
}

export interface StallWarning { level: "err" | "warn"; text: string; }

export function streamStallWarning(s: StallFields): StallWarning | null {
  if (s.state !== "recording") return null;
  if (s.stream_stalled) {
    const age = Math.floor(s.last_frame_age_s ?? 0);
    return {
      level: "err",
      text: `No thermal frames for ${age} s: the camera stream has stalled. The recording is still open but capturing nothing and will be marked not complete. Check the camera connection, or stop the recording.`,
    };
  }
  const n = s.stream_stalls ?? 0;
  if (n > 0) {
    return {
      level: "warn",
      text: `The camera stream stalled ${n}× earlier in this run; frames are arriving again. The gaps are listed in manifest.json (stream_stalls) and the run will be marked not complete.`,
    };
  }
  return null;
}
