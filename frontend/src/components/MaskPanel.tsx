import { regionPixelCount, type MaskAction, type MaskState } from "../lib/mask.ts";

interface Props {
  state: MaskState;
  dispatch: (a: MaskAction) => void;
  maskMode: boolean;
  onMaskMode: (on: boolean) => void;
  /** Pixels the mask leaves in use (null: no shapes, every pixel counts). */
  usedPx: number | null;
  /** Frame size for the per-region pixel counts (null before the first frame). */
  frame: { w: number; h: number } | null;
}

/**
 * The mask regions, listed in the measurements panel under the ROI rows. The mask only decides
 * which pixels set the colour auto-range and the frame stats; the data and ROI readouts are
 * untouched. Clicking a row turns on mask mode and selects that region on the image.
 */
export function MaskPanel({ state, dispatch, maskMode, onMaskMode, usedPx, frame }: Props) {
  const n = state.shapes.length;
  const select = (id: number) => {
    if (!maskMode) onMaskMode(true);
    dispatch({ type: "edit", action: { type: "select", id } });
  };
  return (
    <div className="mask-panel">
      <div className="mask-head">
        <b>mask</b>
        {n > 0 && (
          <span className="muted">
            {`${n} region${n > 1 ? "s" : ""} · `}
            {state.enabled && usedPx !== null ? `${usedPx.toLocaleString()} px used` : "off: every pixel counts"}
          </span>
        )}
        <label title="Off keeps the regions but uses every pixel again">
          <input type="checkbox" checked={state.enabled} disabled={n === 0} onChange={(e) => dispatch({ type: "setEnabled", enabled: e.target.checked })} /> on
        </label>
        <span role="radiogroup" aria-label="new mask regions">
          new regions:{" "}
          {(["include", "exclude"] as const).map((m) => (
            <label key={m} style={{ marginRight: 6 }}>
              <input type="radio" name="mask-draw-mode" checked={state.drawMode === m} onChange={() => dispatch({ type: "setDrawMode", mode: m })} /> {m}
            </label>
          ))}
        </span>
      </div>
      {n === 0
        ? <div className="muted">no mask: press ◩ and draw the area you want to see</div>
        : (
          <ul className="mask-list">
            {state.shapes.map((m) => (
              <li key={m.id} className={maskMode && state.selected === m.id ? "selected" : ""} onClick={() => select(m.id)} tabIndex={0}
                onKeyDown={(e) => { if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); dispatch({ type: "remove", id: m.id }); } }}
                title="Click to select it on the image (mask mode); Delete removes it">
                <span className={`mask-chip ${m.mode}`} aria-hidden="true" />
                <span className="mask-name">{m.mode} {m.id} · {m.kind}</span>
                <span className="v">{frame ? `${regionPixelCount(m, frame.w, frame.h).toLocaleString()} px` : ""}</span>
                <button className="secondary" onClick={(e) => { e.stopPropagation(); dispatch({ type: "toggleMode", id: m.id }); }} title="Flip include / exclude">flip</button>
                <button className="secondary" onClick={(e) => { e.stopPropagation(); dispatch({ type: "remove", id: m.id }); }} aria-label={`Remove mask region ${m.mode} ${m.id}`}>×</button>
              </li>
            ))}
          </ul>
        )}
    </div>
  );
}
