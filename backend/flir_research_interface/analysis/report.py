"""One-file PDF report per run (ResearchIR/Research Studio "report"): page 1 the README text,
then the ROI plot and the preview image, each as a full page. Pillow only (no reportlab); the
pages are rendered as images, so the text is not selectable but every viewer opens it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from flir_research_interface.analysis.run_summary import readme_text
from flir_research_interface.playback.reader import ExperimentReader

PAGE = (1240, 1754)  # A4 at 150 dpi
MARGIN = 70


def _text_page(text: str) -> Image.Image:
    img = Image.new("RGB", PAGE, "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=20)
    mono = ImageFont.load_default(size=17)
    y = MARGIN
    for line in text.splitlines():
        f = font if (line and not line.startswith(" ")) else mono
        d.text((MARGIN, y), line, fill="black", font=f)
        y += 26 if f is font else 22
        if y > PAGE[1] - MARGIN:
            break
    return img


def _image_page(path: Path, title: str) -> Image.Image | None:
    if not path.is_file():
        return None
    src = Image.open(path).convert("RGB")
    img = Image.new("RGB", PAGE, "white")
    d = ImageDraw.Draw(img)
    d.text((MARGIN, MARGIN - 40), title, fill="black", font=ImageFont.load_default(size=20))
    box_w, box_h = PAGE[0] - 2 * MARGIN, PAGE[1] - 2 * MARGIN
    scale = min(box_w / src.width, box_h / src.height)
    fitted = src.resize((max(1, int(src.width * scale)), max(1, int(src.height * scale))))
    img.paste(fitted, (MARGIN, MARGIN))
    return img


def write_report(reader: ExperimentReader) -> dict[str, Any]:
    """Write ``exports/report.pdf``; returns {"path", "pages"}."""
    pages: list[Image.Image] = [_text_page(readme_text(reader))]
    for rel, title in (
        ("exports/roi_plot.png", "ROI temperature vs time"),
        ("preview.png", "Mid-recording frame (iron palette)"),
        ("keyframes.png", "Keyframes"),
    ):
        page = _image_page(reader.path / rel, title)
        if page is not None:
            pages.append(page)
    out_dir = reader.path / "exports"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / "report.pdf"
    pages[0].save(path, format="PDF", save_all=True, append_images=pages[1:], resolution=150)
    return {"path": str(path), "pages": len(pages), "size_bytes": path.stat().st_size}


__all__ = ["write_report"]
