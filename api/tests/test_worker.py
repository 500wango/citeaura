import sys
import types
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.db import Base
from api.models import Job, Project, Tenant
from api.worker import tasks
from api.worker.celery_app import celery_app


def test_celery_registers_all_pipeline_tasks():
    registered = set(celery_app.tasks)

    assert {
        "disvorai.bootstrap",
        "disvorai.sample",
        "disvorai.cycle",
        "disvorai.verify",
        "disvorai.deliver",
    } <= registered


def test_bootstrap_task_uses_tenant_context(monkeypatch):
    calls = []

    @contextmanager
    def fake_context(tenant_id, project_slug, keys=None):
        calls.append((tenant_id, project_slug))
        yield

    fake_bootstrap = types.SimpleNamespace(run=lambda slug, skip_llm=False: {"slug": slug, "skip_llm": skip_llm})
    monkeypatch.setitem(sys.modules, "bootstrap", fake_bootstrap)
    monkeypatch.setattr(tasks, "with_tenant_context", fake_context)
    monkeypatch.setattr(tasks, "_job_status", lambda *args, **kwargs: _empty_context())

    result = tasks.task_bootstrap.run("tenant-a", "example", skip_llm=True)

    assert result == {"slug": "example", "skip_llm": True}
    assert calls == [("tenant-a", "example")]


def test_find_job_rejects_cross_tenant_or_wrong_action(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'worker.sqlite'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with session_factory() as db:
        first_tenant = Tenant(name="tenant-a", plan="trial")
        second_tenant = Tenant(name="tenant-b", plan="trial")
        db.add_all([first_tenant, second_tenant])
        db.flush()
        first_project = Project(
            tenant_id=first_tenant.id,
            slug="first-project",
            url="https://first.example",
            market="both",
        )
        second_project = Project(
            tenant_id=second_tenant.id,
            slug="second-project",
            url="https://second.example",
            market="both",
        )
        db.add_all([first_project, second_project])
        db.flush()
        first_job = Job(project_id=first_project.id, action="sample", status="queued")
        second_job = Job(project_id=second_project.id, action="sample", status="queued")
        db.add_all([first_job, second_job])
        db.commit()

        assert tasks._find_job(db, "tenant-a", "first-project", "sample", first_job.id).id == first_job.id
        assert tasks._find_job(db, "tenant-a", "first-project", "sample", second_job.id) is None
        assert tasks._find_job(db, "tenant-a", "first-project", "verify", first_job.id) is None


@contextmanager
def _empty_context():
    yield
