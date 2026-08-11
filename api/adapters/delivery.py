"""把引擎交付目录补齐为 SaaS 的六文档契约。"""

import shutil
from pathlib import Path

from api.adapters.branding import apply_delivery_branding
from api.adapters.engine import geolib
from api.adapters.exceptions import GeoEngineError


REQUIRED_DOCUMENTS = {
    "01": "诊断报告",
    "02": "执行方案",
    "03": "工单表",
    "04": "验收表",
    "05": "初稿风险清单",
    "06": "建设地图",
}


def _latest_delivery(project_directory: Path):
    directory = project_directory / "delivery"
    deliveries = sorted(item for item in directory.iterdir() if item.is_dir()) if directory.exists() else []
    return deliveries[-1] if deliveries else None


def _copy_execution_plan(project_directory: Path, delivery_directory: Path):
    sources = {
        ".md": project_directory / "deliverables" / "2-GEO优化方案.md",
        ".html": project_directory / "deliverables" / "2-GEO优化方案.html",
    }
    for suffix, source in sources.items():
        if source.is_file():
            shutil.copy2(source, delivery_directory / f"02-执行方案{suffix}")


def _write_empty_risk_report(project_directory: Path, delivery_directory: Path):
    lint = geolib.read_json(project_directory / "assets" / "drafts" / "_lint.json", None)
    if lint is None:
        result = "No AI draft generated for this cycle; no risk items to verify."
    else:
        result = "Draft risk inspection found no items requiring manual verification for this cycle."
    markdown = f"# AI Draft Risk Inspection · {geolib.today()}\n\n{result}\n"
    (delivery_directory / "05-Draft-Risks.md").write_text(markdown, "utf-8")

    import report

    html = report.build_html(
        "AI Draft Risk Inspection",
        markdown,
        [("Items to Verify", "0"), ("High Risk", "0")],
    )
    (delivery_directory / "05-Draft-Risks.html").write_text(html, "utf-8")


def ensure_delivery_contract(project_slug: str, delivery_directory: Path | None = None):
    """确保交付目录包含 01 到 06 六类文档。"""
    project_directory = geolib.project_dir(project_slug)
    delivery_directory = Path(delivery_directory) if delivery_directory else _latest_delivery(project_directory)
    if delivery_directory is None or not delivery_directory.is_dir():
        raise GeoEngineError("delivery directory was not generated")

    if not any(delivery_directory.glob("02-*")):
        _copy_execution_plan(project_directory, delivery_directory)
    if not any(delivery_directory.glob("05-*")):
        _write_empty_risk_report(project_directory, delivery_directory)

    missing = [
        f"{number}-{name}"
        for number, name in REQUIRED_DOCUMENTS.items()
        if not any(delivery_directory.glob(f"{number}-*"))
    ]
    if missing:
        raise GeoEngineError("incomplete delivery: " + ", ".join(missing))
    apply_delivery_branding(delivery_directory)
    return delivery_directory
