"""One-file PDF report per run: the README text, the ROI plot and the preview image."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from flir_research_interface.api.app import create_app
from tests.test_run_summary import _exp


def test_report_pdf_has_text_plot_and_preview_pages(tmp_path: Path) -> None:
    r = _exp(tmp_path)
    from flir_research_interface.analysis.report import write_report
    from flir_research_interface.analysis.run_summary import write_run_summary

    write_run_summary(r)
    info = write_report(r)
    pdf = Path(info["path"])
    assert pdf == r.path / "exports" / "report.pdf" and pdf.stat().st_size > 5000
    assert info["pages"] >= 2
    head = pdf.read_bytes()[:8]
    assert head.startswith(b"%PDF")


def test_report_route(tmp_path: Path) -> None:
    r = _exp(tmp_path)
    with TestClient(create_app(experiments_root=tmp_path)) as c:
        j = c.post(f"/api/experiments/{r.path.name}/export/report").json()
        assert j["path"].endswith("report.pdf")
        g = c.get(f"/api/experiments/{r.path.name}/report.pdf")
        assert g.status_code == 200 and g.headers["content-type"] == "application/pdf"
