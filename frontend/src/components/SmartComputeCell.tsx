// The compute / reload button, progress bar and job text of one smart ROI row in playback.
import type { SmartComputeAction, SmartJob } from "../lib/smartSeries.ts";

interface Props {
  label: string;
  act: SmartComputeAction | null;
  job: SmartJob | null;
  text: string | null;
  onAct: () => void;
}

export function SmartComputeCell({ label, act, job, text, onAct }: Props) {
  return (
    <div className="smart-compute">
      {act && <button className="secondary" type="button" disabled={act.disabled} onClick={onAct}
        title="Track this smart ROI over every frame of the run (full rate) and store the result with the run">{act.label}</button>}
      {job?.state === "running" && job.total > 0 && <progress max={job.total} value={job.done} aria-label={`computing ${label}`} />}
      {text && <span className={job?.state === "error" ? "smart-error" : "hint"}>{text}</span>}
    </div>
  );
}
