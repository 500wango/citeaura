"""投影表可重建与幂等测试。"""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.adapters import engine as engine_adapter
from api.adapters.engine import geolib, with_tenant_context
from api.db import Base
from api.models import Project, ProjectionState, PromptProjection, RunProjection, SampleProjection, Tenant
from api.projections.rebuild import rebuild_index


def _row(question, round_number, mention):
    return {
        "run_id": "run-1",
        "question_id": question,
        "platform": "openai",
        "sample_mode": "api",
        "round": round_number,
        "ok": True,
        "raw_model": "gpt-test",
        "search_enabled": False,
        "answer": "Acme is useful.",
        "analysis": {"brand_mentioned": mention, "brand_rank": 1 if mention else 0},
    }


@pytest.fixture()
def projection_env(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    engine = create_engine(f"sqlite:///{tmp_path / 'projection.sqlite'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        tenant = Tenant(name="tenant", directory_slug="tenant", plan="pro")
        db.add(tenant)
        db.flush()
        project = Project(tenant_id=tenant.id, slug="project", url="https://example.com")
        db.add(project)
        db.commit()
        tenant_id, project_id = tenant.id, project.id
    with with_tenant_context("tenant", "project"):
        directory = geolib.project_dir("project")
        geolib.write_json(directory / "geo.json", {
            "brand": {"name": "Acme", "site": "https://example.com"},
            "questions": [
                {"id": "q001", "text": "Best tool?", "market": "global", "group": "recommendation"},
            ],
        })
        (directory / "samples").mkdir(parents=True, exist_ok=True)
        (directory / "metrics").mkdir(parents=True, exist_ok=True)
        (directory / "samples" / "run-1.jsonl").write_text(
            "\n".join(json.dumps(_row("q001", index + 1, index < 3)) for index in range(5)) + "\n",
            "utf-8",
        )
        geolib.write_json(directory / "metrics" / "run-1.json", {
            "run_id": "run-1", "question_count": 1, "sample_count": 5,
            "successful_sample_count": 5,
        })
    yield Session, tenant_id, project_id, directory
    engine.dispose()


def test_rebuild_is_idempotent_and_reports_changes(projection_env):
    Session, tenant_id, project_id, directory = projection_env
    with Session() as db:
        first = rebuild_index(db, tenant_id, project_id, directory)
        second = rebuild_index(db, tenant_id, project_id, directory)
        assert first["changed"] is True
        assert first["samples"] == 5
        assert second["changed"] is False
        runs = db.query(RunProjection).filter(RunProjection.project_id == project_id).all()
        samples = db.query(SampleProjection).filter(SampleProjection.project_id == project_id).all()
        prompts = db.query(PromptProjection).filter(PromptProjection.project_id == project_id).all()
        assert len(runs) == 1
        assert len(samples) == 5
        assert len(prompts) == 1
        assert runs[0].source_sha256


def test_dry_run_does_not_write(projection_env):
    Session, tenant_id, project_id, directory = projection_env
    with Session() as db:
        result = rebuild_index(db, tenant_id, project_id, directory, dry_run=True)
        assert result["changed"] is True
        assert result["dry_run"] is True
        assert db.query(RunProjection).count() == 0


def test_duplicate_sample_rows_collapse(projection_env):
    Session, tenant_id, project_id, directory = projection_env
    path = directory / "samples" / "run-1.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_row("q001", 1, True)) + "\n")
    with Session() as db:
        rebuild_index(db, tenant_id, project_id, directory, force=True)
        assert db.query(SampleProjection).filter(SampleProjection.project_id == project_id).count() == 5


def test_failure_rolls_back_and_marks_error(projection_env, monkeypatch):
    Session, tenant_id, project_id, directory = projection_env
    from api.projections import rebuild as rebuild_module

    def explode(*args, **kwargs):
        raise RuntimeError("projection write failed")

    monkeypatch.setattr(rebuild_module, "sync_run", explode)
    with Session() as db:
        with pytest.raises(RuntimeError):
            rebuild_index(db, tenant_id, project_id, directory, force=True)
    with Session() as db:
        state = db.query(ProjectionState).filter(ProjectionState.project_id == project_id).one()
        assert state.status == "error"
        assert "projection write failed" in state.last_error
        assert db.query(RunProjection).count() == 0


def test_removed_run_is_cleaned(projection_env):
    Session, tenant_id, project_id, directory = projection_env
    with Session() as db:
        rebuild_index(db, tenant_id, project_id, directory)
    (directory / "metrics" / "run-1.json").unlink()
    (directory / "samples" / "run-1.jsonl").unlink()
    with Session() as db:
        rebuild_index(db, tenant_id, project_id, directory, force=True)
        assert db.query(RunProjection).filter(RunProjection.project_id == project_id).count() == 0
        assert db.query(SampleProjection).filter(SampleProjection.project_id == project_id).count() == 0
