from pathlib import Path

import pytest

from api.adapters import delivery
from api.adapters.exceptions import GeoEngineError


def _seed_delivery(tmp_path: Path):
    project = tmp_path / "example"
    output = project / "delivery" / "2026-07-31"
    output.mkdir(parents=True)
    for number, name in (("01", "诊断报告"), ("03", "工单表"), ("04", "验收表"), ("06", "建设地图")):
        (output / f"{number}-{name}.html").write_text(number, "utf-8")
    plan = project / "deliverables" / "2-GEO优化方案.md"
    plan.parent.mkdir()
    plan.write_text("# Execution plan\n", "utf-8")
    return project, output


def test_delivery_contract_fills_plan_and_empty_risk_report(tmp_path, monkeypatch):
    project, output = _seed_delivery(tmp_path)
    monkeypatch.setattr(delivery.geolib, "project_dir", lambda slug: project)
    monkeypatch.setattr(delivery.geolib, "today", lambda: "2026-07-31")

    result = delivery.ensure_delivery_contract("example", output)

    assert result == output
    assert (output / "02-执行方案.md").read_text("utf-8") == "# Execution plan\n"
    risk = (output / "05-初稿风险清单.md").read_text("utf-8")
    assert "本期未生成 AI 初稿" in risk
    assert (output / "05-初稿风险清单.html").is_file()
    assert {path.name[:2] for path in output.iterdir() if path.is_file()} == set(delivery.REQUIRED_DOCUMENTS)


def test_delivery_contract_rejects_missing_core_document(tmp_path, monkeypatch):
    project, output = _seed_delivery(tmp_path)
    (output / "06-建设地图.html").unlink()
    monkeypatch.setattr(delivery.geolib, "project_dir", lambda slug: project)
    monkeypatch.setattr(delivery.geolib, "today", lambda: "2026-07-31")

    with pytest.raises(GeoEngineError, match="06-建设地图"):
        delivery.ensure_delivery_contract("example", output)
