import sys
import types
from contextlib import contextmanager

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


@contextmanager
def _empty_context():
    yield

