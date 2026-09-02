import { useState } from "react";
import type { AlignmentAction, AlignmentState } from "../lib/alignment.ts";
import { Disclosure } from "./Disclosure.tsx";

interface Props {
  state: AlignmentState;
  dispatch: (a: AlignmentAction) => void;
  calibrating: boolean;
  onCalibrating: (on: boolean) => void;
  irSize: [number, number] | null;
  onSave: () => Promise<string>;
  /** Leave calibration and switch the visible camera to overlay mode so the result is seen at once. */
  onFinishOverlay: () => void;
}

/** Visible↔IR alignment: pick the same features on both images, fit a homography, apply. */
export function AlignmentPanel({ state, dispatch, calibrating, onCalibrating, irSize, onSave, onFinishOverlay }: Props) {
  const [msg, setMsg] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "failed">("idle");
  const n = state.pairs.length;
  const solved = state.H !== null && state.rmsPx !== null;
  return (
    <>
      <div className="row">
        <button className={calibrating ? "danger" : "secondary"} onClick={() => onCalibrating(!calibrating)}>{calibrating ? "finish aligning" : "align cameras…"}</button>
        <span className="hint">{state.H ? `aligned · ${n} pairs · RMS ${state.rmsPx?.toFixed(1)} px` : n ? `${n} pair${n > 1 ? "s" : ""} picked, not solved` : "not aligned (scale/shift only)"}</span>
      </div>
      {calibrating && (
        <>
          <ul className="help">
            <li>The images show side by side. Click a feature in the IR image, then the same feature in the visible image; that makes one pair.</li>
            <li>Use features on the sample surface at its working distance (the alignment is for that plane). Spread them over the field: corners of the crucible, electrode edges, fiducials.</li>
            <li>4 pairs is the minimum; 6 to 8 spread out gives a better fit. Solve, read the RMS, then finish.</li>
          </ul>
          <div className="kv">
            {state.pairs.map((p, i) => [
              <span key={`k${i}`}>pair {i + 1}</span>,
              <span key={`v${i}`} className="v plain" style={{ display: "flex", justifyContent: "flex-end", gap: 6 }}>
                <small>IR ({p.ir[0].toFixed(3)}, {p.ir[1].toFixed(3)}) · vis ({p.visible[0].toFixed(3)}, {p.visible[1].toFixed(3)})</small>
                <button className="secondary" aria-label={`remove pair ${i + 1}`} onClick={() => dispatch({ type: "removePair", index: i })}>×</button>
              </span>,
            ])}
          </div>
          <div className="row">
            <button className="primary" disabled={n < 4 || !irSize} onClick={() => { if (irSize) { dispatch({ type: "solve", irSize }); setSaveState("idle"); setMsg(null); } }}>{solved ? "re-solve" : `solve (${n}/4)`}</button>
            <button className="secondary" disabled={n === 0 && !state.pending} onClick={() => dispatch({ type: "clear" })}>clear pairs</button>
          </div>
          {solved && (
            <div className={state.rmsPx! > 5 ? "warnbox" : "okbox"} role="status">
              <b>Solved.</b> {n} pairs, RMS error {state.rmsPx!.toFixed(2)} px on the IR image.
              {state.rmsPx! <= 5 ? " The overlay now uses this alignment." : " That is large: check for a mismatched pair or off-plane features."}
              <div className="row" style={{ marginTop: 6 }}>
                <button className="primary" onClick={onFinishOverlay}>finish &amp; show overlay</button>
                <button className="secondary" disabled={saveState === "saving" || saveState === "saved"} onClick={() => { setSaveState("saving"); onSave().then((m) => { setSaveState("saved"); setMsg(m); }).catch((e) => { setSaveState("failed"); setMsg(String(e)); }); }}>
                  {saveState === "saved" ? "saved on operator ✓" : saveState === "saving" ? "saving…" : "save to operator"}
                </button>
              </div>
            </div>
          )}
          <div className="row">
            <input type="text" value={state.note} placeholder="note, e.g. sample plane at 0.45 m" style={{ flex: 1, minWidth: 120 }} onChange={(e) => dispatch({ type: "note", note: e.target.value })} />
          </div>
          {msg && <div className={saveState === "failed" ? "errbox" : "hint"}>{msg}</div>}
        </>
      )}
      {!calibrating && (
        <Disclosure label="Why a homography, and its limits" icon="info">
          <ul className="help">
            <li>The visible camera sits beside the IR camera, so the two views differ by perspective, not just size and position.</li>
            <li>A homography maps one plane exactly: pick features on the sample surface, and the overlay lines up there.</li>
            <li>Objects nearer or farther than that plane still show parallax. Re-align if the working distance changes.</li>
            <li>The alignment in force is written into each recording's metadata.</li>
          </ul>
        </Disclosure>
      )}
    </>
  );
}
