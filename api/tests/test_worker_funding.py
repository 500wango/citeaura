import base64
import os
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.adapters.engine import load_tenant_keys
from api.db import Base
from api.models import ApiKey, Project, Tenant
from api.settings.crypto import encrypt_key
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
            encrypted_value=encrypt_key("worker-only-secret"),
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


def test_explicit_sampling_platform_without_worker_funding_is_blocked():
    funding = {
        "tenant_id": 7,
        "keys": {"custom_gateway": "secret"},
        "pool_codes": frozenset(),
    }
    with pytest.raises(tasks.SamplingPlatformUnavailable, match="sampling_platform_unavailable:deepseek"):
        tasks._validate_requested_platforms(["deepseek", "custom_gateway"], funding)
