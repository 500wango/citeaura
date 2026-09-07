import base64
import os
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.adapters.engine import load_tenant_keys
from api.db import Base
from api.models import ApiKey, Project, Tenant
from api.settings.crypto import encrypt_key, key_aad
from api.worker import tasks


@pytest.fixture()
def worker_database(tmp_path, monkeypatch):
    monkeypatch.setenv("AES_KEY", base64.urlsafe_b64encode(b"1" * 32).decode())
    engine = create_engine(f"sqlite:///{tmp_path / 'worker-funding.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with factory() as db:
        tenant = Tenant(name="Numeric Workspace", directory_slug="12345", plan="trial")
        db.add(tenant)
        db.flush()
        db.add(Project(
            tenant_id=tenant.id,
            slug="citeaura-com",
            url="https://citeaura.com",
            market="global",
        ))
        db.add(ApiKey(
            tenant_id=tenant.id,
            engine_code="deepseek",
            encrypted_value=encrypt_key("worker-only-secret", key_aad(tenant.id, "deepseek")),
        ))
        db.commit()
        tenant_id = tenant.id
    yield factory, tenant_id


def test_worker_funding_reads_byok_by_directory_slug(worker_database, monkeypatch):
    factory, tenant_id = worker_database
    monkeypatch.setattr(tasks, "SessionLocal", factory)
    monkeypatch.setattr(tasks, "_engine_custom_providers", lambda tenant_id: [])
    monkeypatch.setattr(tasks, "ensure_global_engine_scope", lambda slug: None)
    monkeypatch.setattr(tasks, "_sync_custom_provider_scope", lambda slug, providers: None)
    monkeypatch.setattr(tasks, "record_usage", lambda *args, **kwargs: [])

    @contextmanager
    def no_meter(codes):
        yield {}

    monkeypatch.setattr(tasks, "meter_platform_calls", no_meter)

    with factory() as db:
        assert load_tenant_keys(db, "12345") == {"deepseek": "worker-only-secret"}

    with tasks._funded_engine_context("12345", "citeaura-com", "sample") as funding:
        assert funding["tenant_id"] == tenant_id
        assert funding["tenant_directory_slug"] == "12345"
        assert os.environ["DEEPSEEK_API_KEY"] == "worker-only-secret"

    assert "DEEPSEEK_API_KEY" not in os.environ


def test_load_tenant_keys_uses_integer_ids_even_when_another_slug_matches(worker_database):
    factory, tenant_id = worker_database
    with factory() as db:
        db.add(Tenant(name="Conflicting Workspace", directory_slug=str(tenant_id), plan="trial"))
        db.flush()
        conflicting = db.query(Tenant).filter(Tenant.directory_slug == str(tenant_id)).one()
        db.add(ApiKey(
            tenant_id=conflicting.id,
            engine_code="deepseek",
            encrypted_value=encrypt_key("conflicting-secret", key_aad(conflicting.id, "deepseek")),
        ))
        db.commit()

        assert load_tenant_keys(db, tenant_id) == {"deepseek": "worker-only-secret"}


def test_completed_pool_work_fails_when_usage_cannot_be_recorded_or_persisted(monkeypatch):
    @contextmanager
    def empty_context(*args, **kwargs):
        yield

    @contextmanager
    def pool_calls(codes):
        yield {"deepseek": 1}

    monkeypatch.setattr(tasks, "_engine_funding", lambda *args, **kwargs: {
        "tenant_id": 1,
        "tenant_directory_slug": "tenant-a",
        "keys": {},
        "pool_codes": frozenset(("deepseek",)),
    })
    monkeypatch.setattr(tasks, "_engine_custom_providers", lambda *args, **kwargs: [])
    monkeypatch.setattr(tasks, "with_tenant_context", empty_context)
    monkeypatch.setattr(tasks, "ensure_global_engine_scope", lambda slug: None)
    monkeypatch.setattr(tasks, "_sync_funded_engine_scope", lambda *args: None)
    monkeypatch.setattr(tasks, "_sync_custom_provider_scope", lambda *args: None)
    monkeypatch.setattr(tasks, "meter_platform_calls", pool_calls)
    monkeypatch.setattr(tasks, "record_usage", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db down")))
    monkeypatch.setattr(tasks, "persist_usage_outbox", lambda *args, **kwargs: 0)
    monkeypatch.setattr(tasks.time, "sleep", lambda *args: None)

    with pytest.raises(RuntimeError, match="platform_usage_accounting_pending"):
        with tasks._funded_engine_context("tenant-a", "citeaura-com", "sample", job_id=7):
            pass


def test_explicit_sampling_platform_without_worker_funding_is_blocked():
    funding = {
        "tenant_id": 7,
        "keys": {"custom_gateway": "secret"},
        "pool_codes": frozenset(),
    }
    with pytest.raises(tasks.SamplingPlatformUnavailable, match="sampling_platform_unavailable:deepseek"):
        tasks._validate_requested_platforms(["deepseek", "custom_gateway"], funding)


def test_sync_funded_engine_scope_adds_global_api_and_keeps_existing_platforms(tmp_path, monkeypatch):
    config_path = tmp_path / "geo.json"
    config_path.write_text("{}", encoding="utf-8")
    config = {
        "platforms": ["openai", "custom_old"],
        "questions": [],
    }
    saved = []
    monkeypatch.setattr(tasks.geolib, "project_dir", lambda slug: tmp_path)
    monkeypatch.setattr(tasks.geolib, "load_config", lambda slug: dict(config))
    monkeypatch.setattr(tasks.geolib, "save_config", lambda slug, value: saved.append(value))

    tasks._sync_funded_engine_scope("citeaura-com", {"deepseek", "custom_new", "glm"})

    assert saved == [{
        "platforms": ["openai", "custom_old", "deepseek"],
        "questions": [],
    }]


def test_funded_context_syncs_funded_global_and_custom_platforms(tmp_path, monkeypatch):
    config_path = tmp_path / "geo.json"
    config_path.write_text("{}", encoding="utf-8")
    config = {
        "platforms": ["openai", "custom_old"],
        "questions": [],
    }
    saved = []
    current = dict(config)
    provider = {
        "code": "custom_new",
        "name": "New Gateway",
        "model_id": "vendor/new-model",
    }
    monkeypatch.setattr(tasks.geolib, "project_dir", lambda slug: tmp_path)

    def load_config(slug):
        return current

    def save_config(slug, value):
        snapshot = dict(value)
        current.clear()
        current.update(snapshot)
        saved.append(snapshot)

    monkeypatch.setattr(tasks.geolib, "load_config", load_config)
    monkeypatch.setattr(tasks.geolib, "save_config", save_config)
    monkeypatch.setattr(tasks, "_engine_funding", lambda *args, **kwargs: {
        "keys": {"deepseek": "secret"},
        "pool_codes": frozenset(),
        "tenant_id": 1,
        "tenant_directory_slug": "tenant-a",
    })
    monkeypatch.setattr(tasks, "_engine_custom_providers", lambda *args, **kwargs: [provider])
    monkeypatch.setattr(tasks, "ensure_global_engine_scope", lambda slug: None)

    @contextmanager
    def empty_context():
        yield

    monkeypatch.setattr(tasks, "with_tenant_context", lambda *args, **kwargs: empty_context())
    monkeypatch.setattr(tasks, "meter_platform_calls", lambda codes: empty_context())
    monkeypatch.setattr(tasks, "record_usage", lambda *args, **kwargs: None)

    with tasks._funded_engine_context("tenant-a", "citeaura-com", "sample"):
        pass

    assert saved[-1]["platforms"] == ["openai", "deepseek", "custom_new"]
    assert "custom_old" not in saved[-1]["platforms"]
    assert saved[-1]["provider_model_ids"] == {"custom_new": "vendor/new-model"}


def test_sync_custom_provider_scope_persists_model_id_without_secret(tmp_path, monkeypatch):
    config = {"platforms": ["openai", "custom_old"]}
    saved = []
    (tmp_path / "geo.json").write_text("{}", encoding="utf-8")
    provider = {
        "code": "custom_new",
        "name": "New Gateway",
        "model_id": "vendor/new-model",
    }
    monkeypatch.setattr(tasks.geolib, "project_dir", lambda slug: tmp_path)
    monkeypatch.setattr(tasks.geolib, "load_config", lambda slug: dict(config))
    monkeypatch.setattr(tasks.geolib, "save_config", lambda slug, value: saved.append(value))

    tasks._sync_custom_provider_scope("citeaura-com", [provider])

    assert saved == [{
        "platforms": ["openai", "custom_new"],
        "provider_labels": {"custom_new": "New Gateway"},
        "provider_model_ids": {"custom_new": "vendor/new-model"},
    }]
    assert "api_key" not in saved[0]
