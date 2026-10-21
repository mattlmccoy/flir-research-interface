"""Post-run analysis of the visible camera around the sample: the runner.

Reads each visible segment with ffmpeg (a luma crop around the sample and, when there is one, the
bed), measures every frame after the start-up skip with :mod:`.visible_sample`, and writes to the
run's ``exports/``: ``visible_sample.json`` always, and when the video could be analysed also
``visible_sample.csv``, one contrast-stretched close-up video per segment and the timeline plot
``visible_sample_plot.png``. The JSON says what happened (``ok``, ``skipped`` or ``failed``, with a
reason); a run that was not analysed never leaves results of an earlier analysis beside it. The plot
is derived from the rest: if only it cannot be drawn the run stays ``ok``, without the plot, and
the JSON's ``plot_error`` says why. Nothing here touches the recording itself.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import shutil
import subprocess
from collections import Counter
from collections.abc import Generator, Iterator
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from flir_research_interface import __version__
from flir_research_interface.analysis.visible_overlay import ir_to_visible_coeffs
from flir_research_interface.analysis.visible_sample import (
    coverage,
    find_events,
    flash_threshold,
    frame_metrics,
    ir_to_visible_points,
    otsu_threshold,
    pick_rois,
    region_mask,
    roi_outline_ir,
)
from flir_research_interface.analysis.visible_sample_plot import visible_sample_plot_png
from flir_research_interface.playback.reader import ExperimentReader
from flir_research_interface.playback.visible_timing import FRAME0_SKIP_S, thermal_segments
from flir_research_interface.visible.recorder import FFMPEG_CANDIDATES
from flir_research_interface.visible.rtsp import find_ffprobe

logger = logging.getLogger(__name__)

JSON_NAME = "visible_sample.json"
CSV_NAME = "visible_sample.csv"
PLOT_NAME = "visible_sample_plot.png"
CLOSEUP_STEM = "visible_sample_closeup"
CSV_COLUMNS = (
    "t_s",
    "segment",
    "frame",
    "keyframe",
    "sample_dark_px",
    "sample_mean_luma",
    "bed_clipped_frac",
    "brightening",
)
MARGIN_PX = 30  # the analysis region is the mapped sample ROI grown by this many visible pixels
THRESHOLD_WINDOW_S = 5.0  # the run's dark threshold comes from this much video from the start
FLOOR, K, MAD_FLOOR, MERGE_S = 15.0, 6.0, 1.0, 1.0  # the flash rule (see visible_sample)
STRETCH_HI = 250  # close-up: luma from the run's sample luma up to this maps to 0-255
CLOSEUP_SCALE = 3
BLOCK_PX = 16  # an event's bounding box is made of blocks this size
_MAX_COORD_FACTOR = 10  # a mapped ROI farther than this many frame widths is not an alignment


class _Skip(Exception):  # noqa: N818 - a control-flow signal, not an error
    """The video cannot be analysed for a known reason; ``reason`` goes into the JSON."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class _Packets:
    """What ffprobe says about one video file: frame size and per-packet time and keyframe flag."""

    width: int
    height: int
    pts_s: np.ndarray
    keyframe: np.ndarray


@dataclass(frozen=True)
class _Seg:
    """One video file on the thermal time axis: ``t_start_s`` is where its first packet falls."""

    index: int
    name: str
    path: Path
    t_start_s: float
    pts_s: np.ndarray
    keyframe: np.ndarray


@dataclass(frozen=True)
class _Plan:
    """Everything the analysis needs, fixed before the first frame is decoded.

    ``box`` is the sample region in the frame (x0, y0, w, h) and ``mask`` its pixels; ``crop`` is
    what is decoded: the union of that and the bed region. ``region`` and ``bed_mask`` are the two
    masks in the shape of the crop. ``missing`` names the files visible.json lists that are not on
    disk; ``alignment`` says which saved alignment mapped the ROI.
    """

    ffmpeg: str
    sample: dict[str, Any]
    bed: dict[str, Any] | None
    vis_size: tuple[int, int]
    segments: list[_Seg]
    box: tuple[int, int, int, int]
    mask: np.ndarray
    crop: tuple[int, int, int, int]
    region: np.ndarray
    bed_mask: np.ndarray | None
    missing: list[str]
    alignment: dict[str, Any]


# -- ffprobe and ffmpeg -------------------------------------------------------------------------


def _probe(ffprobe: str, path: Path) -> _Packets:
    """Frame size and the display time and keyframe flag of every packet of ``path``.

    The recorder's stream is Baseline H.264 (no B-frames), so packet order is display order; a file
    where times go backwards is refused rather than analysed on a wrong time axis.
    """
    cmd = [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries"]
    cmd += ["packet=pts_time,flags:stream=width,height", "-of", "json", str(path)]
    run = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if run.returncode != 0:
        raise RuntimeError(f"ffprobe failed (rc {run.returncode}): {run.stderr.strip()[-300:]}")
    doc = json.loads(run.stdout)
    packets, streams = doc.get("packets") or [], doc.get("streams") or []
    if not packets or not streams:
        raise ValueError(f"{path.name} has no video packets")
    pts = np.array([float(p["pts_time"]) for p in packets])
    if np.any(np.diff(pts) < 0):
        raise ValueError(f"packet times in {path.name} are not in display order")
    key = np.array(["K" in str(p.get("flags", "")) for p in packets], dtype=bool)
    return _Packets(int(streams[0]["width"]), int(streams[0]["height"]), pts, key)


def _decode_luma(
    ffmpeg: str, path: Path, crop: tuple[int, int, int, int]
) -> Iterator[np.ndarray]:
    """Yield the luma crop ``(x, y, w, h)`` of every frame of ``path`` as a ``(h, w)`` uint8 array.

    ``-fps_mode passthrough`` gives exactly one frame per packet (the default inserts duplicates,
    which would shift every later time). Closing the generator early stops ffmpeg.
    """
    x, y, w, h = crop
    cmd = [ffmpeg, "-v", "fatal", "-nostdin", "-i", str(path)]
    cmd += ["-vf", f"extractplanes=y,crop={w}:{h}:{x}:{y}", "-fps_mode", "passthrough"]
    cmd += ["-f", "rawvideo", "-"]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    assert proc.stdout is not None and proc.stderr is not None
    try:
        while len(buf := proc.stdout.read(w * h)) == w * h:
            yield np.frombuffer(buf, dtype=np.uint8).reshape(h, w)
        if proc.wait() != 0:
            tail = proc.stderr.read().decode(errors="replace")[-300:]
            raise RuntimeError(f"ffmpeg decode failed (rc {proc.returncode}): {tail}")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        proc.stdout.close()
        proc.stderr.close()


def _closeup_box(
    box: tuple[int, int, int, int], vis_size: tuple[int, int]
) -> tuple[int, int, int]:
    """``(x, y, side)`` of the close-up crop: a square of even size centred on the sample region,
    moved to stay inside the frame, at an even position (the chroma planes are half size)."""
    x0, y0, w, h = box
    side = max(w, h)
    side = min(side + side % 2, min(vis_size) // 2 * 2)
    x = min(max(round(x0 + w / 2 - side / 2), 0), vis_size[0] - side)
    y = min(max(round(y0 + h / 2 - side / 2), 0), vis_size[1] - side)
    return x - x % 2, y - y % 2, side


def _closeup_command(
    ffmpeg: str, src: Path, out: Path, crop: tuple[int, int, int], lo: float
) -> list[str]:
    """ffmpeg argv for the close-up: drop the start-up skip, crop, stretch luma ``lo``..250 to
    0..255, scale x3 (Lanczos), and keep every remaining frame at its source time (the video starts
    at the first frame that was analysed, not at 0).

    The source's frames are irregular (1 ms to 840 ms apart on the real run), so: ``passthrough``
    neither drops nor duplicates; ``-enc_time_base -1`` keeps the encoder on the source's own time
    base (the default is 1 / the average frame rate, about 98 ms, and frames that land on the same
    tick are merged and the rest shift); and ``-bf 0`` stores frames in display order, so a seek to
    a frame's time lands on that frame.
    """
    x, y, side = crop
    ramp = f"clip((val-{lo:g})*255/({STRETCH_HI}-{lo:g}),0,255)"
    size = CLOSEUP_SCALE * side
    vf = (
        f"select='gte(t,{FRAME0_SKIP_S:g})',crop={side}:{side}:{x}:{y},"
        f"lutyuv=y='{ramp}',scale={size}:{size}:flags=lanczos"
    )
    cmd = [ffmpeg, "-v", "error", "-nostdin", "-y", "-i", str(src), "-vf", vf]
    cmd += ["-fps_mode", "passthrough", "-enc_time_base", "-1"]
    return cmd + ["-c:v", "libx264", "-bf", "0", "-crf", "20", "-pix_fmt", "yuv420p"] + [
        "-an", "-f", "mp4", str(out)
    ]  # fmt: skip


def _encode_closeup(
    ffmpeg: str, src: Path, out: Path, crop: tuple[int, int, int], lo: float
) -> None:
    run = subprocess.run(
        _closeup_command(ffmpeg, src, out, crop, lo), capture_output=True, text=True
    )
    if run.returncode != 0:
        raise RuntimeError(f"ffmpeg close-up failed (rc {run.returncode}): {run.stderr[-300:]}")


# -- geometry -----------------------------------------------------------------------------------


def _map_outline(
    roi: dict[str, Any],
    h_matrix: list[list[float]],
    ir_size: tuple[int, int],
    vis_size: tuple[int, int],
) -> np.ndarray | None:
    """The ROI outline in visible pixels, or ``None`` when the alignment cannot place it.

    That is a singular matrix, a point at or behind the line at infinity (homogeneous w <= 0), a
    non-finite result, or a point more than ``_MAX_COORD_FACTOR`` frame widths away.
    """
    try:
        ir = roi_outline_ir(roi)
        with np.errstate(all="ignore"):
            *_, g, h = ir_to_visible_coeffs(h_matrix, *ir_size, *vis_size)
            if not np.all(ir @ np.array([g, h]) + 1.0 > 0):
                return None
            pts = ir_to_visible_points(ir, h_matrix, ir_size, vis_size)
    except (np.linalg.LinAlgError, ValueError, TypeError):
        return None
    if not np.all(np.isfinite(pts)) or np.abs(pts).max() > _MAX_COORD_FACTOR * max(vis_size):
        return None
    return pts


def _ir_size(reader: ExperimentReader) -> tuple[int, int]:
    """Width and height of the thermal frames, which the ROIs are drawn in (A70: 640x480)."""
    if reader.n_frames == 0:
        return 640, 480
    _, h, w = reader.counts_block(0, 1).shape
    return int(w), int(h)


def _place(mask: np.ndarray, at: tuple[int, int], shape: tuple[int, int]) -> np.ndarray:
    out = np.zeros(shape, dtype=bool)
    out[at[1] : at[1] + mask.shape[0], at[0] : at[0] + mask.shape[1]] = mask
    return out


def _plan(reader: ExperimentReader, ffmpeg: str | None, ffprobe: str | None) -> _Plan:
    """Check the inputs, probe the video, and fix the regions. Raises ``_Skip`` with the reason."""
    timeline = thermal_segments(reader.visible, reader.host_t0_ns)
    files = [s for s in timeline if (reader.path / s["file"]).is_file()]
    missing = [str(s["file"]) for s in timeline if s not in files]
    if missing:
        logger.warning("visible.json lists segments that are not on disk: %s", ", ".join(missing))
    if not files:
        raise _Skip("no visible video")
    saved = reader.metadata.get("visible_alignment") or {}
    h_matrix = saved.get("H")
    if not h_matrix:
        raise _Skip("no visible alignment")
    sample, bed = pick_rois(reader.metadata.get("rois"))
    if sample is None:
        raise _Skip("no sample ROI (name containing 'sample')")
    ffmpeg_exe = shutil.which(ffmpeg) if ffmpeg else find_ffprobe(FFMPEG_CANDIDATES)
    if not ffmpeg_exe:
        raise _Skip("ffmpeg not found")
    ffprobe_exe = shutil.which(ffprobe) if ffprobe else find_ffprobe()
    if not ffprobe_exe:
        raise _Skip("ffprobe not found")
    segments, sizes = [], set()
    for s in files:
        packets = _probe(ffprobe_exe, reader.path / s["file"])
        sizes.add((packets.width, packets.height))
        segments.append(
            _Seg(
                int(s["index"]),
                str(s["file"]),
                reader.path / s["file"],
                float(s["t_start_s"]),
                packets.pts_s,
                packets.keyframe,
            )
        )
    if len(sizes) != 1:
        raise ValueError(f"visible segments differ in frame size: {sorted(sizes)}")
    vis_size = sizes.pop()
    ir_size = _ir_size(reader)
    outline = _map_outline(sample, h_matrix, ir_size, vis_size)
    if outline is None:
        raise _Skip("visible alignment is invalid")
    region = region_mask(outline, MARGIN_PX, vis_size)
    if region is None:
        raise _Skip("sample ROI maps outside the visible frame")
    mask, box = region
    bed_region = None  # the bed is optional: one that cannot be placed in the frame is left out
    if bed is not None:
        bed_outline = _map_outline(bed, h_matrix, ir_size, vis_size)
        bed_region = None if bed_outline is None else region_mask(bed_outline, 0, vis_size)
    boxes = [box] + ([bed_region[1]] if bed_region else [])
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[0] + b[2] for b in boxes), max(b[1] + b[3] for b in boxes)
    crop = (x0, y0, x1 - x0, y1 - y0)
    shape = (crop[3], crop[2])
    return _Plan(
        ffmpeg=ffmpeg_exe,
        sample=sample,
        bed=bed if bed_region else None,
        vis_size=vis_size,
        segments=segments,
        box=box,
        mask=mask,
        crop=crop,
        region=_place(mask, (box[0] - x0, box[1] - y0), shape),
        bed_mask=_place(bed_region[0], (bed_region[1][0] - x0, bed_region[1][1] - y0), shape)
        if bed_region
        else None,
        missing=missing,
        alignment={
            "saved_utc": saved.get("saved_utc"),
            "rmsPx": saved.get("rmsPx"),
            "n_pairs": len(saved["pairs"]) if isinstance(saved.get("pairs"), list) else None,
        },
    )


# -- measuring ----------------------------------------------------------------------------------


def _analysed(plan: _Plan, seg: _Seg) -> Generator[tuple[int, float, np.ndarray], None, None]:
    """``(frame index, seconds since the segment's first packet, luma crop)`` for each frame after
    the start-up skip. Decodes them all; fails when the frame count differs from the packet count
    (a missing or extra frame would put every later time on the wrong frame)."""
    n = len(seg.pts_s)
    decoded = 0
    for decoded, luma in enumerate(_decode_luma(plan.ffmpeg, seg.path, plan.crop), start=1):
        if decoded > n:
            break
        rel = float(seg.pts_s[decoded - 1] - seg.pts_s[0])
        if rel >= FRAME0_SKIP_S:
            yield decoded - 1, rel, luma
    if decoded != n:
        raise RuntimeError(
            f"decoded frame count {decoded} differs from packet count {n} in {seg.name}"
        )


def _threshold(plan: _Plan) -> int:
    """The run's dark threshold: Otsu over the sample region of the analysed frames within the
    first ``THRESHOLD_WINDOW_S`` of the first segment (the next one, if that has none)."""
    for seg in plan.segments:
        pixels, first = [], None
        with closing(_analysed(plan, seg)) as frames:
            for _, rel, luma in frames:
                first = rel if first is None else first
                if rel - first > THRESHOLD_WINDOW_S:
                    break
                pixels.append(luma[plan.region])
        if pixels:
            return otsu_threshold(np.concatenate(pixels))
    raise ValueError(f"no frame to analyse: the video ends within the first {FRAME0_SKIP_S} s")


def _block_reduce(a: np.ndarray) -> np.ndarray:
    """Sum of ``a`` over ``BLOCK_PX`` x ``BLOCK_PX`` blocks (the edge blocks are partial)."""
    h, w = a.shape
    padded = np.zeros((-(-h // BLOCK_PX) * BLOCK_PX, -(-w // BLOCK_PX) * BLOCK_PX), dtype=a.dtype)
    padded[:h, :w] = a
    n = BLOCK_PX
    return np.asarray(padded.reshape(padded.shape[0] // n, n, padded.shape[1] // n, n).sum(
        axis=(1, 3), dtype=np.int32
    ))


def _block_change(plan: _Plan, luma: np.ndarray, prev: np.ndarray) -> np.ndarray:
    """Per block, the summed luma change since ``prev`` over the sample region's pixels."""
    x, y, w, h = plan.box
    ox, oy = x - plan.crop[0], y - plan.crop[1]
    win = (slice(oy, oy + h), slice(ox, ox + w))
    change = luma[win].astype(np.int16) - prev[win].astype(np.int16)
    change[~plan.mask] = 0
    return _block_reduce(change)


def _measure(
    plan: _Plan, threshold: int
) -> tuple[list[dict[str, Any]], list[np.ndarray | None], np.ndarray]:
    """One row per analysed frame in time order; the block changes of each (``None`` for a
    segment's first); and a histogram of the luma of the sample's dark pixels over the run."""
    rows: list[dict[str, Any]] = []
    blocks: list[np.ndarray | None] = []
    dark_hist = np.zeros(256, dtype=np.int64)
    for seg in plan.segments:
        prev = None  # the previous analysed frame of this segment, never a skipped one
        for i, rel, luma in _analysed(plan, seg):
            m = frame_metrics(luma, prev, plan.region, threshold, plan.bed_mask)
            key = bool(seg.keyframe[i])
            rows.append(
                {
                    "t_s": round(seg.t_start_s + rel, 6),
                    "segment": seg.index,
                    "frame": i,
                    "keyframe": key,
                    "sample_dark_px": m.sample_dark_px,
                    "sample_mean_luma": m.sample_mean_luma,
                    "bed_clipped_frac": m.bed_clipped_frac,
                    "brightening": None if key else m.brightening,  # the encoder's refresh
                }
            )
            blocks.append(None if prev is None else _block_change(plan, luma, prev))
            pixels = luma[plan.region]
            dark_hist += np.bincount(pixels[pixels < threshold], minlength=256)
            prev = luma
    return rows, blocks, dark_hist


def _hist_percentile(hist: np.ndarray, q: float) -> float | None:
    """The ``q``-th percentile (linear interpolation, as ``np.percentile``) of the values counted
    by ``hist`` (``hist[v]`` = how many times the value ``v`` occurs); ``None`` with no value."""
    n = int(hist.sum())
    if n == 0:
        return None
    pos = (n - 1) * q / 100.0
    k = int(pos)
    cum = np.cumsum(hist)
    lo = int(np.searchsorted(cum, k, side="right"))
    hi = int(np.searchsorted(cum, min(k + 1, n - 1), side="right"))
    return lo + (pos - k) * (hi - lo)


def _stretch_lo(dark_hist: np.ndarray) -> float:
    """The close-up's black level: the 1st percentile of the sample's dark-pixel luma over the run,
    kept under ``STRETCH_HI`` so the ramp has a slope; 0 when no pixel was ever dark."""
    p1 = _hist_percentile(dark_hist, 1.0)
    return 0.0 if p1 is None else round(min(p1, STRETCH_HI - 1.0), 2)


def _flash_bbox(
    sums: np.ndarray, counts: np.ndarray, window: tuple[int, int, int, int]
) -> dict[str, int] | None:
    """Where a frame brightened: the box (visible pixels) around the blocks whose mean luma change
    is at least half that of the block that brightened most; ``None`` if nothing brightened.

    ``sums`` is the summed change per block and ``counts`` the region pixels per block; ``window``
    is the region's box ``(x0, y0, w, h)``, which the block grid starts at.
    """
    mean = np.divide(sums, counts, out=np.zeros(sums.shape), where=counts > 0)
    top = float(mean.max())
    if top <= 0:
        return None
    rows, cols = np.nonzero(mean >= top / 2)
    x0, y0, w, h = window
    left, upper = int(cols.min()) * BLOCK_PX, int(rows.min()) * BLOCK_PX
    right = min((int(cols.max()) + 1) * BLOCK_PX, w)
    lower = min((int(rows.max()) + 1) * BLOCK_PX, h)
    return {"x0": x0 + left, "y0": y0 + upper, "w": right - left, "h": lower - upper}


# -- results ------------------------------------------------------------------------------------


def _summary(
    plan: _Plan,
    rows: list[dict[str, Any]],
    blocks: list[np.ndarray | None],
    threshold: int,
    lo: float,
) -> dict[str, Any]:
    """The JSON of an analysed run (``files`` is filled in once the files are written)."""
    t = np.array([r["t_s"] for r in rows])
    if np.any(np.diff(t) < 0):  # find_events merges flagged frames in the order given
        raise ValueError("visible segments are not in time order on the thermal axis")
    key = np.array([r["keyframe"] for r in rows], dtype=bool)
    bright = np.array([np.nan if r["brightening"] is None else r["brightening"] for r in rows])
    flash = flash_threshold(bright, key, FLOOR, K, MAD_FLOOR)
    counts = _block_reduce(plan.mask.astype(np.int16))
    events = find_events(t, bright, key, flash, MERGE_S)
    for ev in events:
        k = ev["peak_frame"]  # find_events counts in analysed frames; report the file's frame
        sums = blocks[k]
        ev["bbox"] = None if sums is None else _flash_bbox(sums, counts, plan.box)
        ev["peak_frame"], ev["segment"] = rows[k]["frame"], rows[k]["segment"]

    def named(roi: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if roi is None else {"id": roi.get("id"), "name": roi.get("name")}

    per_segment = Counter(r["segment"] for r in rows)
    segments = [
        {
            "index": seg.index,
            "file": seg.name,
            "t_start_s": round(seg.t_start_s, 6),
            "frames_analysed": per_segment[seg.index],
        }
        for seg in plan.segments
    ]
    x0, y0, w, h = plan.box
    return {
        "status": "ok",
        "reason": None,
        "software": __version__,
        "sample_roi": named(plan.sample),
        "bed_roi": named(plan.bed),
        "alignment": plan.alignment,
        "bbox": {"x0": x0, "y0": y0, "w": w, "h": h},
        "margin_px": MARGIN_PX,
        "threshold": threshold,
        "dark_rule": "luma strictly below threshold",
        "flash_threshold": flash,
        "rule": {"floor": FLOOR, "k": K, "mad_floor": MAD_FLOOR, "merge_s": MERGE_S},
        "coverage": coverage(t),
        "segments": segments,
        "missing": plan.missing,
        "events": events,
        "stretch": {"lo": lo, "hi": STRETCH_HI},
        "plot_error": None,
        "files": [],
    }


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(int(value))
    return repr(round(value, 6)) if isinstance(value, float) else str(value)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_COLUMNS)
        writer.writerows([_cell(r[c]) for c in CSV_COLUMNS] for r in rows)


def _plot_png(
    reader: ExperimentReader, rows: list[dict[str, Any]], summary: dict[str, Any]
) -> bytes | None:
    """The timeline plot, or ``None`` when it could not be drawn: the reason is then put in
    ``summary["plot_error"]`` (the plot is derived, so losing it must not lose the analysis)."""
    try:
        return visible_sample_plot_png(reader, rows, summary)
    except Exception as exc:  # noqa: BLE001 - recorded in the summary, not raised
        logger.exception("visible sample plot failed")
        summary["plot_error"] = f"{type(exc).__name__}: {exc}"
        return None


def _write_json(path: Path, summary: dict[str, Any]) -> None:
    path.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")


class _Staged:
    """Files written as ``<name>.part`` and moved into place together, so a reader never sees a
    half-written result. ``discard`` removes whatever was staged."""

    def __init__(self, folder: Path) -> None:
        self._folder = folder
        self._parts: list[Path] = []

    def part(self, name: str) -> Path:
        path = self._folder / f"{name}.part"
        self._parts.append(path)
        return path

    def commit(self) -> None:
        for path in self._parts:
            os.replace(path, path.with_suffix(""))

    def discard(self) -> None:
        for path in self._parts:
            path.unlink(missing_ok=True)


def _remove_stale(folder: Path, keep: list[str]) -> None:
    """Delete this feature's files (and half-written ``.part`` files) that are not in ``keep``."""
    for pattern in (CSV_NAME, PLOT_NAME, f"{CLOSEUP_STEM}*.mp4", "visible_sample*.part"):
        for path in folder.glob(pattern):
            if path.name not in keep:
                path.unlink(missing_ok=True)


def _write_stopped(folder: Path, status: str, reason: str) -> dict[str, Any]:
    """The JSON of a run that was not analysed; any earlier results are removed."""
    summary: dict[str, Any] = {
        "status": status,
        "reason": reason,
        "software": __version__,
        "files": [JSON_NAME],
    }
    staged = _Staged(folder)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        _remove_stale(folder, [JSON_NAME])
        _write_json(staged.part(JSON_NAME), summary)
        staged.commit()
    except OSError:
        staged.discard()
        logger.exception("could not write %s", folder / JSON_NAME)
    return summary


def _closeup_name(segment_index: int) -> str:
    """``visible_sample_closeup.mp4`` for segment 0, then ``_001``... (like visible_001.mp4)."""
    suffix = "" if segment_index == 0 else f"_{segment_index:03d}"
    return f"{CLOSEUP_STEM}{suffix}.mp4"


def analyse_visible_sample(
    reader: ExperimentReader,
    ffmpeg: str | None = None,
    ffprobe: str | None = None,
    closeup: bool = True,
) -> dict[str, Any]:
    """Analyse the visible video of ``reader``'s run around the sample; write ``exports/``.

    Returns the summary also written to ``exports/visible_sample.json``: ``status`` is ``ok``,
    ``skipped`` (an input is missing: ``reason`` says which) or ``failed`` (``reason`` is
    ``"<ExceptionType>: <message>"``). Never raises. An analysed run gets ``visible_sample.csv``
    (one row per analysed frame), a close-up video per segment (unless ``closeup`` is false) and the
    JSON, all moved into place together; any other run has the JSON only, and no older result.
    ``ffmpeg`` and ``ffprobe`` are executables; unset, they are looked for.
    """
    folder = reader.path / "exports"
    staged = _Staged(folder)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        plan = _plan(reader, ffmpeg, ffprobe)
        threshold = _threshold(plan)
        rows, blocks, dark_hist = _measure(plan, threshold)
        lo = _stretch_lo(dark_hist)
        summary = _summary(plan, rows, blocks, threshold, lo)
        files = [CSV_NAME]
        _write_csv(staged.part(CSV_NAME), rows)
        if closeup:
            crop = _closeup_box(plan.box, plan.vis_size)
            for seg in plan.segments:
                name = _closeup_name(seg.index)
                _encode_closeup(plan.ffmpeg, seg.path, staged.part(name), crop, lo)
                files.append(name)
        if (png := _plot_png(reader, rows, summary)) is not None:
            staged.part(PLOT_NAME).write_bytes(png)
            files.append(PLOT_NAME)
        summary["files"] = [*files, JSON_NAME]
        _write_json(staged.part(JSON_NAME), summary)
        staged.commit()
        _remove_stale(folder, summary["files"])
        logger.info("visible sample: %d frames, %d events", len(rows), len(summary["events"]))
        return summary
    except _Skip as skip:
        staged.discard()
        logger.info("visible sample analysis skipped: %s", skip.reason)
        return _write_stopped(folder, "skipped", skip.reason)
    except Exception as exc:  # noqa: BLE001 - a failure is a result, never an error for the caller
        staged.discard()
        logger.exception("visible sample analysis failed")
        return _write_stopped(folder, "failed", f"{type(exc).__name__}: {exc}")


__all__ = ["analyse_visible_sample"]
