import sys
import types
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
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
        "disvorai.pipeline",
        "disvorai.dispatch_schedules",
    } <= registered
    assert celery_app.conf.beat_schedule["dispatch-due-project-schedules"]["task"] == "disvorai.dispatch_schedules"


def test_bootstrap_task_uses_tenant_context(monkeypatch):
    calls = []

    @contextmanager
    def fake_context(tenant_id, project_slug, keys=None):
        calls.append((tenant_id, project_slug))
        yield

    def fake_autopilot(args):
        calls.append(("autopilot", args.slug, args.skip_llm, args.no_sample, args.limit))

    @contextmanager
    def fake_preserve(project_slug):
        calls.append(("preserve", project_slug))
        yield

    monkeypatch.setitem(sys.modules, "geo", types.SimpleNamespace(cmd_autopilot=fake_autopilot))
    monkeypatch.setattr(tasks, "with_tenant_context", fake_context)
    monkeypatch.setattr(tasks, "preserve_manual_tickets", fake_preserve)
    monkeypatch.setattr(tasks, "ensure_delivery_contract", lambda slug: calls.append(("delivery", slug)))
    monkeypatch.setattr(tasks, "_job_status", lambda *args, **kwargs: _empty_context())

    result = tasks.task_bootstrap.run("tenant-a", "example", skip_llm=True, no_sample=True)

    assert result == {"status": "done", "action": "bootstrap", "project_slug": "example"}
    assert calls == [
        ("tenant-a", "example"),
        ("preserve", "example"),
        ("autopilot", "example", True, True, None),
        ("delivery", "example"),
    ]


def test_pipeline_task_dispatches_whitelisted_geo_action(monkeypatch):
    calls = []

    @contextmanager
    def fake_context(tenant_id, project_slug, keys=None):
        calls.append(("context", tenant_id, project_slug, keys))
        yield

    def fake_serve(args):
        calls.append(("serve", args.slug, args.max_pages, args.limit, args.no_sample, args.draft))

    @contextmanager
    def fake_preserve(project_slug):
        calls.append(("preserve", project_slug))
        yield

    monkeypatch.setitem(sys.modules, "geo", types.SimpleNamespace(cmd_serve=fake_serve))
    monkeypatch.setattr(tasks, "with_tenant_context", fake_context)
    monkeypatch.setattr(tasks, "preserve_manual_tickets", fake_preserve)
    monkeypatch.setattr(tasks, "ensure_delivery_contract", lambda slug: calls.append(("delivery", slug)))
    monkeypatch.setattr(tasks, "_engine_keys", lambda tenant_id: {"deepseek": "secret"})
    monkeypatch.setattr(tasks, "_job_status", lambda *args, **kwargs: _empty_context())

    result = tasks.task_pipeline.run(
        "tenant-a",
        "example",
        "serve",
        params={"--max-pages": 8, "limit": 3, "--draft": True, "ignored": "value"},
    )

    assert result == {"status": "done", "action": "serve", "project_slug": "example"}
    assert calls == [
        ("context", "tenant-a", "example", {"deepseek": "secret"}),
        ("preserve", "example"),
        ("serve", "example", 8, 3, False, True),
        ("delivery", "example"),
    ]
    with pytest.raises(ValueError, match="unsupported pipeline action"):
        tasks._action_namespace("publish", {})
    with pytest.raises(ValueError, match="must be between 1 and 1000"):
        tasks._action_namespace("sample", {"limit": 0})


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


def test_job_status_updates_project_on_success_and_failure(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'status.sqlite'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with session_factory() as db:
        tenant = Tenant(name="tenant-a", plan="trial")
        db.add(tenant)
        db.flush()
        project = Project(
            tenant_id=tenant.id,
            slug="example",
            url="https://example.com",
            market="both",
            status="bootstrapping",
        )
        db.add(project)
        db.flush()
        bootstrap_job = Job(project_id=project.id, action="bootstrap", status="queued")
        db.add(bootstrap_job)
        db.commit()
        bootstrap_job_id = bootstrap_job.id
        project_id = project.id

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(
        tasks,
        "job_log_path",
        lambda tenant_id, project_slug, job_id: tmp_path / "logs" / f"{job_id}.log",
    )
    with tasks._job_status("tenant-a", "example", "bootstrap", bootstrap_job_id):
        print("engine output")
    with session_factory() as db:
        assert db.get(Job, bootstrap_job_id).status == "done"
        assert db.get(Project, project_id).status == "ready"
        verify_job = Job(project_id=project_id, action="verify", status="queued")
        db.add(verify_job)
        db.commit()
        verify_job_id = verify_job.id

    with pytest.raises(RuntimeError, match="verification failed"):
        with tasks._job_status("tenant-a", "example", "verify", verify_job_id):
            raise RuntimeError("verification failed")
    with session_factory() as db:
        assert db.get(Job, verify_job_id).status == "failed"
        assert db.get(Project, project_id).status == "failed"

    bootstrap_log = (tmp_path / "logs" / f"{bootstrap_job_id}.log").read_text("utf-8")
    verify_log = (tmp_path / "logs" / f"{verify_job_id}.log").read_text("utf-8")
    assert "bootstrap started" in bootstrap_log
    assert "engine output" in bootstrap_log
    assert "bootstrap done" in bootstrap_log
    assert "verify failed: RuntimeError: verification failed" in verify_log


def test_schedule_dispatcher_enqueues_due_projects_and_respects_guards(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'dispatch.sqlite'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    with session_factory() as db:
        pro = Tenant(name="pro-tenant", plan="pro")
        trial = Tenant(name="trial-tenant", plan="trial")
        db.add_all([pro, trial])
        db.flush()
        due = Project(
            tenant_id=pro.id,
            slug="due",
            url="https://due.example",
            status="ready",
            schedule_interval_days=7,
            schedule_next_run_at=now - timedelta(days=1),
        )
        future = Project(
            tenant_id=pro.id,
            slug="future",
            url="https://future.example",
            status="ready",
            schedule_interval_days=14,
            schedule_next_run_at=now + timedelta(days=1),
        )
        busy = Project(
            tenant_id=pro.id,
            slug="busy",
            url="https://busy.example",
            status="processing",
            schedule_interval_days=30,
            schedule_next_run_at=now - timedelta(hours=1),
        )
        limited = Project(
            tenant_id=trial.id,
            slug="limited",
            url="https://limited.example",
            status="ready",
            schedule_interval_days=7,
            schedule_next_run_at=now - timedelta(hours=1),
        )
        db.add_all([due, future, busy, limited])
        db.flush()
        db.add(Job(project_id=busy.id, action="verify", status="running"))
        db.add_all([
            Job(project_id=limited.id, action="sample", status="done"),
            Job(project_id=limited.id, action="cycle", status="done"),
        ])
        db.commit()
        due_id = due.id
        busy_next = busy.schedule_next_run_at
        limited_next = limited.schedule_next_run_at

    calls = []
    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(
        tasks,
        "job_log_path",
        lambda tenant_id, project_slug, job_id: tmp_path / "logs" / f"{job_id}.log",
    )
    monkeypatch.setattr(
        tasks.task_cycle,
        "delay",
        lambda *args, **kwargs: calls.append((args, kwargs)) or types.SimpleNamespace(id="cycle-task"),
    )

    result = tasks.task_dispatch_schedules.run(now.isoformat())

    assert result == {"scanned": 3, "enqueued": 1, "busy": 1, "quota_blocked": 1, "failed": 0}
    assert calls == [(('pro-tenant', 'due'), {'job_id': 4})]
    with session_factory() as db:
        due = db.get(Project, due_id)
        assert due.status == "processing"
        assert due.schedule_last_enqueued_at is not None
        assert due.schedule_next_run_at > now.replace(tzinfo=None)
        assert db.query(Job).filter(Job.project_id == due_id, Job.action == "cycle").one().status == "queued"
        assert db.query(Project).filter(Project.slug == "busy").one().schedule_next_run_at == busy_next
        assert db.query(Project).filter(Project.slug == "limited").one().schedule_next_run_at == limited_next


@contextmanager
def _empty_context():
    yield
