// Floating bulk-action bar; only rendered while in selection mode with a non-empty selection.
export function SelectionBar({
  count, driveConnected, busy, progress, onMove, onTag, onStar, onDelete, onSelectAll, onClear,
}: {
  count: number;
  driveConnected: boolean;
  busy: boolean;
  progress: string | null;
  onMove: (to: "drive" | "local") => void;
  onTag: () => void;
  onStar: (on: boolean) => void;
  onDelete: () => void;
  onSelectAll: () => void;
  onClear: () => void;
}) {
  return (
    <div className="selection-bar" role="toolbar" aria-label="bulk actions">
      <span className="count">{count} selected</span>
      <button className="secondary" onClick={onSelectAll}>select all</button>
      {driveConnected && <button className="secondary" disabled={busy} onClick={() => onMove("drive")}>move to drive →</button>}
      {driveConnected && <button className="secondary" disabled={busy} onClick={() => onMove("local")}>← local</button>}
      <button className="secondary" disabled={busy} onClick={onTag}>tag…</button>
      <button className="secondary" disabled={busy} onClick={() => onStar(true)}>★ star</button>
      <button className="secondary" disabled={busy} onClick={() => onStar(false)}>☆ unstar</button>
      <button className="danger" disabled={busy} onClick={onDelete}>delete</button>
      {progress && <span className="hint">{progress}</span>}
      <button className="secondary" style={{ marginLeft: "auto" }} onClick={onClear}>done</button>
    </div>
  );
}
