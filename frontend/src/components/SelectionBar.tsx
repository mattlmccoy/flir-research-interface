// Prominent floating bulk-action bar. Shown for the whole time selection mode is on (even at 0
// selected, as a "pick some runs" prompt) so the action controls are where you expect them after
// clicking "select". During a bulk op it shows a live "verb k/N" progress bar.
export function SelectionBar({
  count, driveConnected, busy, progress, onMove, onTag, onStar, onDelete, onSelectAll, onClear,
}: {
  count: number;
  driveConnected: boolean;
  busy: boolean;
  progress: { done: number; total: number; verb: string } | null;
  onMove: (to: "drive" | "local") => void;
  onTag: () => void;
  onStar: (on: boolean) => void;
  onDelete: () => void;
  onSelectAll: () => void;
  onClear: () => void;
}) {
  const none = count === 0;
  const pct = progress && progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0;
  return (
    <div className="selection-bar" role="toolbar" aria-label="bulk actions">
      <span className="count">{none ? "select runs to act on them" : `${count} selected`}</span>
      <button className="secondary" onClick={onSelectAll}>select all</button>
      <span className="sep" />
      {driveConnected && <button className="secondary" disabled={busy || none} onClick={() => onMove("drive")}>move to drive →</button>}
      {driveConnected && <button className="secondary" disabled={busy || none} onClick={() => onMove("local")}>← local</button>}
      <button className="secondary" disabled={busy || none} onClick={onTag}>tag…</button>
      <button className="secondary" disabled={busy || none} onClick={() => onStar(true)}>★ star</button>
      <button className="secondary" disabled={busy || none} onClick={() => onStar(false)}>☆ unstar</button>
      <button className="danger" disabled={busy || none} onClick={onDelete}>delete</button>
      <button className="secondary done" onClick={onClear}>done</button>
      {progress && (
        <div className="selection-progress" role="status">
          <span>{progress.verb} {Math.min(progress.done + 1, progress.total)}/{progress.total}…</span>
          <div className="progressbar"><div className="progressbar-fill" style={{ width: `${pct}%` }} /></div>
        </div>
      )}
    </div>
  );
}
