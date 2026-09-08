import { useEffect, useState } from "react";
import { api, type ControlStatus } from "./api.ts";

const POLL_MS = 2000;

/** Poll GET /api/control/status. Drives RF/closed-loop UI: `engaged` is true only while the RF
 *  generator (T&C/CXN tool) is actually linked to FLIR (recent RF edge or control tick), so that
 *  UI can hide itself when nothing is linked instead of showing stale state. */
export function useControlStatus(pollMs = POLL_MS): ControlStatus | null {
  const [status, setStatus] = useState<ControlStatus | null>(null);
  useEffect(() => {
    let alive = true;
    const tick = () => api.controlStatus().then((s) => { if (alive) setStatus(s); }).catch(() => {});
    tick();
    const id = setInterval(tick, pollMs);
    return () => { alive = false; clearInterval(id); };
  }, [pollMs]);
  return status;
}
