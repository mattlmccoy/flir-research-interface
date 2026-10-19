import type { MaskAction, MaskState } from "../lib/mask.ts";

interface Props {
  state: MaskState;
  dispatch: (a: MaskAction) => void;
  maskMode: boolean;
  onMaskMode: (on: boolean) => void;
  /** Pixels the mask leaves in use (null: no shapes, every pixel counts). */
  usedPx: number | null;
  totalPx: number | null;
}

/**
 * Region mask controls (rail, display section). The mask only decides which pixels set the colour
 * auto-range and the frame stats; the recorded data and the ROI readouts are untouched.
 */
export function MaskPanel({ state, dispatch, maskMode, onMaskMode, usedPx, totalPx }: Props) {
  const n = state.shapes.length;
  return (
    <div className="mask-panel">
      <div className="row" style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <b>region mask</b>
        <label title="Off keeps the shapes but uses every pixel again">
          <input type="checkbox" checked={state.enabled} disabled={n === 0} onChange={(e) => dispatch({ type: "setEnabled", enabled: e.target.checked })} /> on
        </label>
        <button className={maskMode ? "primary" : "secondary"} onClick={() => onMaskMode(!maskMode)} aria-pressed={maskMode}>{maskMode ? "drawing mask…" : "draw"}</button>
        <span role="radiogroup" aria-label="new mask regions">
          {(["include", "exclude"] as const).map((m) => (
            <label key={m} style={{ marginRight: 6 }}>
              <input type="radio" name="mask-draw-mode" checked={state.drawMode === m} onChange={() => dispatch({ type: "setDrawMode", mode: m })} /> {m}
            </label>
          ))}
        </span>
      </div>
      {n === 0
        ? <div className="muted">No mask: the colour range and frame stats use every pixel. Click draw, then use the rectangle, polygon or freehand tool.</div>
        : (
          <>
            <div className="muted">
              {state.enabled && usedPx !== null && totalPx ? `colour range + frame stats use ${usedPx.toLocaleString()} of ${totalPx.toLocaleString()} px` : "mask off: every pixel counts"}
              {" · "}shift-click a region on the image to flip it
            </div>
            <ul className="mask-list">
              {state.shapes.map((m) => (
                <li key={m.id}>
                  <span className={`mask-chip ${m.mode}`}>{m.mode}</span> {m.kind} {m.id}
                  <button className="secondary" onClick={() => dispatch({ type: "toggleMode", id: m.id })} title="Flip include / exclude">flip</button>
                  <button className="secondary" onClick={() => dispatch({ type: "remove", id: m.id })} aria-label={`Remove mask ${m.kind} ${m.id}`}>×</button>
                </li>
              ))}
            </ul>
            <button className="secondary" onClick={() => dispatch({ type: "clear" })}>clear mask</button>
          </>
        )}
    </div>
  );
}
