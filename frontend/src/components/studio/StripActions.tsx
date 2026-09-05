import { useState } from "react";
import { PALETTE_NAMES, paletteGradient, type PaletteName } from "../../lib/palette.ts";
import { IconEye, IconLayers, IconPalette, IconSaveImage } from "./StripIcons.tsx";

interface Props {
  /** Save a PNG snapshot of the current view. */
  onSaveImage: () => void;
  saveDisabled?: boolean;
  /** ROI overlay show/hide. */
  roisHidden: boolean;
  onToggleRois: () => void;
  /** Visible-camera overlay: available, on/off, toggle, and opacity (0-1). */
  hasVisible: boolean;
  visibleOverlayOn: boolean;
  onToggleVisible: () => void;
  overlayOpacity: number;
  onOverlayOpacity: (v: number) => void;
  visibleTip?: string; // shown when the overlay is off (e.g. "…no visible video")
  /** Thermal color palette. */
  palette: PaletteName;
  setPalette: (p: PaletteName) => void;
}

/**
 * The tool-strip action shortcuts shared by the live and playback views: save image, show/hide
 * ROIs, visible-camera overlay (with an opacity flyout), and a color-palette picker (a flyout of
 * gradient swatches that stays open until its button is toggled again). Page-specific shortcuts
 * (media export, regenerate) live alongside this in each page's `extras`.
 */
export function StripActions({
  onSaveImage, saveDisabled = false, roisHidden, onToggleRois,
  hasVisible, visibleOverlayOn, onToggleVisible, overlayOpacity, onOverlayOpacity, visibleTip,
  palette, setPalette,
}: Props) {
  const [paletteOpen, setPaletteOpen] = useState(false);
  return (
    <>
      <button aria-label="Save image" data-tip="Save image — PNG snapshot of this frame with overlays" disabled={saveDisabled} onClick={onSaveImage}><IconSaveImage /></button>
      <button aria-label={roisHidden ? "Show ROIs" : "Hide ROIs"} aria-pressed={roisHidden} className={roisHidden ? "active" : ""} data-tip={roisHidden ? "Show ROI overlays" : "Hide ROI overlays (measurements keep running)"} onClick={onToggleRois}><IconEye off={roisHidden} /></button>
      <span className="strip-pop-anchor">
        <button aria-label="Visible-camera overlay" aria-pressed={visibleOverlayOn} className={visibleOverlayOn ? "active" : ""} data-tip={visibleOverlayOn ? undefined : (hasVisible ? "Overlay the visible camera (opacity slider)" : (visibleTip ?? "No visible camera available"))} disabled={!hasVisible} onClick={onToggleVisible}><IconLayers /></button>
        {hasVisible && visibleOverlayOn && (
          <span className="strip-popover" role="group" aria-label="Visible overlay opacity">
            <input type="range" min={0} max={1} step={0.05} value={overlayOpacity} aria-label="visible camera opacity"
              onChange={(e) => onOverlayOpacity(Number(e.target.value))} />
            <span className="v">{Math.round(overlayOpacity * 100)}%</span>
          </span>
        )}
      </span>
      <span className="strip-pop-anchor">
        <button aria-label="Color palette" aria-pressed={paletteOpen} className={paletteOpen ? "active" : ""} data-tip={paletteOpen ? undefined : `Color palette — ${palette}`} onClick={() => setPaletteOpen((v) => !v)}><IconPalette /></button>
        {paletteOpen && (
          <span className="strip-popover palette-pop" role="listbox" aria-label="Color palette">
            {PALETTE_NAMES.map((name) => (
              <button key={name} role="option" aria-selected={palette === name} className={`palette-opt${palette === name ? " active" : ""}`}
                onClick={() => setPalette(name)} title={name}>
                <span className="sw" style={{ background: paletteGradient(name) }} />
                <span className="nm">{name}</span>
              </button>
            ))}
          </span>
        )}
      </span>
    </>
  );
}
