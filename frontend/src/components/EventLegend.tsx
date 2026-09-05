import { markerLegend } from "../lib/events.ts";
import type { Marker } from "./TimePlot.tsx";

/** A compact key for the timeline event ticks: a colored dot + name per category present in the
 *  run (RF on, RF off, NUC, gap…). Renders nothing when the run has no events. */
export function EventLegend({ markers, className }: { markers: Marker[]; className?: string }) {
  const cats = markerLegend(markers);
  if (!cats.length) return null;
  return (
    <span className={`event-legend${className ? ` ${className}` : ""}`} aria-label="timeline event key">
      {cats.map((c) => (
        <span className="ev" key={c.label}>
          <i className="dot" style={{ background: c.color }} aria-hidden="true" />
          {c.label}
        </span>
      ))}
    </span>
  );
}
