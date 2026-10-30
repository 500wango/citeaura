import json
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.adapters import engine as engine_adapter
from api.adapters.engine import geolib
from api.db import Base, get_db
from api.main import app
from api.models import Membership, Project
from api.searchdata import (
    ai_sources, ga4, ga4_snapshot, oauth, snapshot_store,
)


CONFIG = {
    "brand": {"name": "Acme CRM", "site": "https://acme.example", "aliases": ["AcmeHQ"]},
    "market": "global",
    "questions": [],
}


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.ok = 200 <= status_code < 300
        self.content = json.dumps(self._payload).encode()

    def json(self):
        return self._payload


# ---------- AI 来源表 ----------

def test_ai_sources_normalizes_and_classifies():
    assert ai_sources.normalize_host("WWW.ChatGPT.com.") == "chatgpt.com"
    assert ai_sources.normalize_host("https://m.doubao.com/chat") == "m.doubao.com"
    assert ai_sources.normalize_host("chatgpt.com:443") == "chatgpt.com"
    assert ai_sources.normalize_host("(not set)") is None
    assert ai_sources.normalize_host("") is None

    assert ai_sources.classify("chatgpt.com")["engine_code"] == "openai"
    assert ai_sources.classify("m.chatgpt.com")["engine_code"] == "openai"
    assert ai_sources.classify("chat.openai.com")["engine_code"] == "openai"
    assert ai_sources.classify("yuanbao.tencent.com")["engine_name"] == "腾讯元宝"
    assert ai_sources.classify("google.com") is None
    assert ai_sources.classify("openai.com") is None
    assert ai_sources.classify("example.com") is None


def test_ai_sources_table_is_sorted_unique_and_versioned():
    domains = [domain for domain, _, _ in ai_sources.AI_SOURCES]
    assert domains == sorted(domains)
    assert len(domains) == len(set(domains))
    assert ai_sources.TABLE_VERSION


# ---------- GA4 客户端 ----------

def _fake_admin(monkeypatch, properties, streams, key_events=(), token="ya29.ga4-secret"):
    calls = {"streams": 0}

    def fake_request(method, url, headers=None, json=None, params=None, timeout=None):
        assert headers["Authorization"] == f"Bearer {token}"
        if url.endswith("/accountSummaries"):
            return FakeResponse(200, {"accountSummaries": [
                {"account": "accounts/1", "propertySummaries": properties},
            ]})
        if "/dataStreams" in url:
            calls["streams"] += 1
            property_id = url.split("/v1beta/")[1].split("/dataStreams")[0]
            return FakeResponse(200, {"dataStreams": streams.get(property_id, [])})
        if "/keyEvents" in url:
            return FakeResponse(200, {"keyEvents": list(key_events)})
        return FakeResponse(200, {"timeZone": "America/Los_Angeles"})

    monkeypatch.setattr(ga4.requests, "request", fake_request)
    return calls


def _web_stream(property_id, uri, number="456"):
    return {
        "type": "WEB_DATA_STREAM",
        "name": f"{property_id}/dataStreams/{number}",
        "displayName": "Web",
        "webStreamData": {"defaultUri": uri},
    }


def test_match_properties_exact_parent_and_fallback(monkeypatch):
    properties = [
        {"property": "properties/1", "display_name": "Acme", "account": "accounts/1", "can_edit": True},
        {"property": "properties/2", "display_name": "Blog", "account": "accounts/1", "can_edit": True},
        {"property": "properties/3", "display_name": "Other", "account": "accounts/1", "can_edit": True},
    ]
    streams = {
        "properties/1": [_web_stream("properties/1", "https://www.acme.example")],
        "properties/2": [_web_stream("properties/2", "https://blog.acme.example", "789")],
        "properties/3": [{"type": "WEB_DATA_STREAM", "name": "properties/3/dataStreams/1", "webStreamData": {"defaultUri": ""}}],
    }
    _fake_admin(monkeypatch, properties, streams, token="token")

    matched = ga4.match_properties("https://blog.acme.example", properties, "token")
    by_property = {item["property"]: item for item in matched["matched"]}
    assert by_property["properties/1"]["match_type"] == "parent"
    assert by_property["properties/2"]["match_type"] == "exact"
    assert matched["offered"][0]["match_type"] == "exact"

    none = ga4.match_properties("https://unknown.example", properties, "token")
    assert none["matched"] == []
    assert {item["property"] for item in none["offered"]} == {"properties/1", "properties/2"}


def test_fetch_ai_referrals_uses_28_day_window_and_metrics(monkeypatch):
    seen = []

    def fake_request(method, url, headers=None, json=None, params=None, timeout=None):
        seen.append(json)
        if json.get("dimensions"):
            return FakeResponse(200, {
                "dimensionHeaders": [{"name": "sessionSource"}],
                "metricHeaders": [
                    {"name": "sessions"}, {"name": "totalUsers"}, {"name": "keyEvents"},
                ],
                "rowCount": 2,
                "rows": [
                    {"dimensionValues": [{"value": "chatgpt.com"}],
                     "metricValues": [{"value": "12"}, {"value": "8"}, {"value": "2"}]},
                    {"dimensionValues": [{"value": "perplexity.ai"}],
                     "metricValues": [{"value": "5"}, {"value": "4"}, {"value": "0"}]},
                ],
            })
        return FakeResponse(200, {
            "metricHeaders": [
                {"name": "sessions"}, {"name": "totalUsers"}, {"name": "keyEvents"},
            ],
            "rows": [{"metricValues": [{"value": "1000"}, {"value": "800"}, {"value": "20"}]}],
        })

    monkeypatch.setattr(ga4.requests, "request", fake_request)
    fetched = ga4.fetch_ai_referrals("token", "properties/123", today=date(2026, 10, 30))

    assert fetched["window"] == {"start": "2026-10-02", "end": "2026-10-29", "days": 28}
    assert fetched["rows"][0] == {
        "source": "chatgpt.com", "sessions": 12, "total_users": 8, "key_events": 2,
    }
    assert fetched["site_totals"] == {"sessions": 1000, "total_users": 800, "key_events": 20}
    assert seen[0]["metrics"] == [
        {"name": "sessions"}, {"name": "totalUsers"}, {"name": "keyEvents"},
    ]
    assert seen[0]["dimensions"] == [{"name": "sessionSource"}]


def test_snapshot_aggregates_engines_and_does_not_sum_users():
    choice = {
        "property": "properties/123",
        "display_name": "Acme",
        "stream_id": "properties/123/dataStreams/456",
        "stream_uri": "https://acme.example",
        "stream_host": "acme.example",
        "project_host": "acme.example",
        "match_type": "exact",
        "matched": True,
    }
    fetched = {
        "window": {"start": "2026-10-02", "end": "2026-10-29", "days": 28},
        "rows": [
            {"source": "chatgpt.com", "sessions": 12, "total_users": 8, "key_events": 2},
            {"source": "chat.openai.com", "sessions": 3, "total_users": 2, "key_events": 0},
            {"source": "perplexity.ai", "sessions": 5, "total_users": 4, "key_events": 1},
            {"source": "google.com", "sessions": 500, "total_users": 400, "key_events": 9},
        ],
        "site_totals": {"sessions": 1000, "total_users": 800, "key_events": 20},
        "source_rows": 4,
        "truncated": False,
    }
    snapshot = ga4_snapshot.build_snapshot(
        choice, fetched, {"status": "ok", "count": 1, "error": None},
        {"time_zone": "UTC"}, now=None,
    )

    assert snapshot["ai_totals"]["sessions"] == 20
    assert snapshot["ai_totals"]["total_users"] is None
    assert snapshot["ai_totals"]["share_of_sessions"] == 0.02
    openai = next(item for item in snapshot["engines"] if item["engine_code"] == "openai")
    assert openai["sessions"] == 15
    assert openai["total_users"] is None
    assert openai["sources"] == ["chat.openai.com", "chatgpt.com"]
    perplexity = next(item for item in snapshot["engines"] if item["engine_code"] == "perplexity")
    assert perplexity["total_users"] == 4
    assert snapshot["coverage"] == {
        "source_rows": 4, "recognized_rows": 3, "unrecognized_rows": 1, "truncated": False,
    }
    assert snapshot["no_ai_traffic"] is False


def test_snapshot_zero_site_sessions_and_no_ai_traffic():
    choice = {
        "property": "properties/1", "display_name": "Acme",
        "stream_id": "properties/1/dataStreams/1", "stream_uri": "https://acme.example",
        "stream_host": "acme.example", "project_host": "acme.example",
        "match_type": "exact", "matched": True,
    }
    fetched = {
        "window": {"start": "2026-10-02", "end": "2026-10-29", "days": 28},
        "rows": [], "site_totals": {"sessions": 0, "total_users": 0, "key_events": 0},
        "source_rows": 0, "truncated": False,
    }
    snapshot = ga4_snapshot.build_snapshot(choice, fetched, None)
    assert snapshot["ai_totals"]["share_of_sessions"] is None
    assert snapshot["no_ai_traffic"] is True


# ---------- 快照存储 ----------

def test_snapshot_store_delete_keeps_the_other_flow(tmp_path):
    work = tmp_path / "work" / "tenant-a"
    with geolib.scoped_paths(tmp_path / "engine", work):
        snapshot_store.write("acme", "gsc_snapshot.json", {"schema_version": 1})
        snapshot_store.write("acme", "ga4_snapshot.json", {"schema_version": 1})

        assert snapshot_store.delete("acme", "ga4_snapshot.json") is True
        assert snapshot_store.read("acme", "gsc_snapshot.json", 1) == {"schema_version": 1}
        assert snapshot_store.read("acme", "ga4_snapshot.json", 1) is None

        assert snapshot_store.delete("acme", "gsc_snapshot.json") is True
        assert not (work / "acme" / "searchdata").exists()


def test_snapshot_store_rotates_only_matching_history(tmp_path):
    work = tmp_path / "work" / "tenant-a"
    with geolib.scoped_paths(tmp_path / "engine", work):
        for _ in range(7):
            snapshot_store.write("acme", "ga4_snapshot.json", {"schema_version": 1})
        history = work / "acme" / "searchdata" / "history"
        assert len(list(history.glob("ga4_snapshot-*.json"))) == snapshot_store.HISTORY_KEEP


# ---------- OAuth ----------

def test_ga4_authorization_uses_analytics_scope_and_flow_bound_state(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    url = oauth.authorization_url(1, 2, 3, oauth.FLOW_GA4)
    query = parse_qs(urlparse(url).query)
    assert query["scope"] == [oauth.GA4_SCOPE]
    state = query["state"][0]
    assert oauth.peek_flow(state) == oauth.FLOW_GA4
    assert oauth.verify_state(state, oauth.FLOW_GA4)[:3] == (1, 2, 3)

    with pytest.raises(oauth.OAuthError) as exc:
        oauth.verify_state(state, oauth.FLOW_GSC)
    assert str(exc.value) == "gsc_state_invalid"


def test_ga4_exchange_rejects_missing_scope_and_revokes(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    revoked = []

    def fake_post(url, data=None, timeout=None):
        if url == oauth.GOOGLE_REVOKE_ENDPOINT:
            revoked.append(data["token"])
            return FakeResponse(200, {})
        return FakeResponse(200, {"access_token": "ya29.partial", "scope": oauth.GSC_SCOPE})

    monkeypatch.setattr(oauth.requests, "post", fake_post)
    oauth._redis().set("citeaura:ga4:pkce:nonce-1", "verifier", ex=60, nx=True)
    with pytest.raises(oauth.OAuthError) as exc:
        oauth.exchange_code("code", "nonce-1", oauth.FLOW_GA4)
    assert str(exc.value) == "ga4_scope_not_granted"
    assert revoked == ["ya29.partial"]


def test_legacy_gsc_state_without_flow_still_verifies(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    from api.auth.security import create_token
    state = create_token(1, 2, oauth.STATE_TOKEN_TYPE, oauth.STATE_TTL, {"pid": 3, "nonce": "n"})
    assert oauth.peek_flow(state) == oauth.FLOW_GSC
    assert oauth.verify_state(state, oauth.FLOW_GSC)[:3] == (1, 2, 3)


# ---------- API 流程 ----------

@pytest.fixture()
def ga4_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://citeaura.test")
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    engine = create_engine(f"sqlite:///{tmp_path / 'ga4.sqlite'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client, sessions, tmp_path
    app.dependency_overrides.clear()


def _register(client, email, tenant_name):
    assert client.post("/api/v1/auth/register", json={
        "email": email, "password": "correct-horse-battery", "tenant_name": tenant_name,
    }).status_code == 202
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "correct-horse-battery"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    me = client.get("/api/v1/me", headers=headers).json()
    return me["tenant"]["id"], me["user"]["id"], headers


def _seed(sessions, tmp_path, tenant_id, tenant_dir):
    with sessions() as db:
        project = Project(tenant_id=tenant_id, slug="acme-example", url="https://acme.example", market="global", status="ready")
        db.add(project)
        db.commit()
        project_id = project.id
    root = tmp_path / "work" / tenant_dir / "acme-example"
    root.mkdir(parents=True)
    (root / "geo.json").write_text(json.dumps({**CONFIG, "slug": "acme-example"}), "utf-8")
    return project_id, root


def _fake_google(monkeypatch, properties, streams, referrals, totals, key_events=(), token="ya29.ga4-secret"):
    revoked = []

    def fake_post(url, data=None, timeout=None):
        if url == oauth.GOOGLE_REVOKE_ENDPOINT:
            revoked.append(data["token"])
            return FakeResponse(200, {})
        return FakeResponse(200, {"access_token": token, "scope": oauth.GA4_SCOPE})

    def fake_request(method, url, headers=None, json=None, params=None, timeout=None):
        assert headers["Authorization"] == f"Bearer {token}"
        if url.endswith("/accountSummaries"):
            return FakeResponse(200, {"accountSummaries": [
                {"account": "accounts/1", "propertySummaries": properties},
            ]})
        if "/dataStreams" in url:
            property_id = url.split("/v1beta/")[1].split("/dataStreams")[0]
            return FakeResponse(200, {"dataStreams": streams.get(property_id, [])})
        if "/keyEvents" in url:
            return FakeResponse(200, {"keyEvents": list(key_events)})
        if url.endswith(":runReport"):
            if json.get("dimensions"):
                return FakeResponse(200, {
                    "dimensionHeaders": [{"name": "sessionSource"}],
                    "metricHeaders": [
                        {"name": "sessions"}, {"name": "totalUsers"}, {"name": "keyEvents"},
                    ],
                    "rowCount": len(referrals),
                    "rows": [
                        {"dimensionValues": [{"value": source}],
                         "metricValues": [{"value": str(s)}, {"value": str(u)}, {"value": str(k)}]}
                        for source, s, u, k in referrals
                    ],
                })
            return FakeResponse(200, {
                "metricHeaders": [
                    {"name": "sessions"}, {"name": "totalUsers"}, {"name": "keyEvents"},
                ],
                "rows": [{"metricValues": [
                    {"value": str(totals["sessions"])}, {"value": str(totals["total_users"])},
                    {"value": str(totals["key_events"])},
                ]}],
            })
        return FakeResponse(200, {"timeZone": "America/Los_Angeles"})

    monkeypatch.setattr(oauth.requests, "post", fake_post)
    monkeypatch.setattr(ga4.requests, "request", fake_request)
    return revoked


def _authorize(client, headers, project_id):
    response = client.post(f"/api/v1/projects/{project_id}/searchdata/ga4/authorize", headers=headers)
    assert response.status_code == 200, response.text
    return parse_qs(urlparse(response.json()["authorization_url"]).query)["state"][0]


def _callback(client, state, **params):
    return client.get(
        "/api/v1/searchdata/gsc/callback",
        params={"state": state, "code": "auth-code", **params},
        follow_redirects=False,
    )


PROPERTIES = [
    {"property": "properties/123", "displayName": "Acme", "propertyType": "PROPERTY_TYPE_ORDINARY", "parent": "accounts/1"},
]
STREAMS = {"properties/123": [_web_stream("properties/123", "https://acme.example")]}
REFERRALS = (("chatgpt.com", 12, 8, 2), ("perplexity.ai", 5, 4, 0), ("google.com", 100, 90, 3))
TOTALS = {"sessions": 1000, "total_users": 800, "key_events": 20}


def test_single_match_writes_snapshot_and_revokes_token(ga4_client, monkeypatch):
    client, sessions, tmp_path = ga4_client
    tenant_id, _, headers = _register(client, "owner@acme.example", "tenant-a")
    project_id, root = _seed(sessions, tmp_path, tenant_id, "tenant-a")
    revoked = _fake_google(monkeypatch, PROPERTIES, STREAMS, REFERRALS, TOTALS,
                           key_events=[{"eventName": "purchase"}])

    response = _callback(client, _authorize(client, headers, project_id))
    assert response.status_code == 303
    location = response.headers["location"]
    assert "#/report?ga4=ready" in location and f"project={project_id}" in location
    assert revoked == ["ya29.ga4-secret"]

    summary = client.get(f"/api/v1/projects/{project_id}/searchdata/ga4", headers=headers).json()
    assert summary["status"] == "ready"
    assert summary["source_label"] == "GA4·第一方"
    assert summary["property"] == "properties/123"
    assert summary["ai_totals"]["sessions"] == 17
    assert summary["ai_totals"]["total_users"] is None
    assert summary["coverage"]["unrecognized_rows"] == 1
    assert summary["key_events"]["status"] == "ok"
    assert summary["ai_sources_version"] == ai_sources.TABLE_VERSION

    snapshot_file = root / "searchdata" / "ga4_snapshot.json"
    assert snapshot_file.is_file()
    assert "ya29.ga4-secret" not in snapshot_file.read_text("utf-8")


def test_multiple_matches_require_single_use_selection(ga4_client, monkeypatch):
    client, sessions, tmp_path = ga4_client
    tenant_id, _, headers = _register(client, "owner@acme.example", "tenant-a")
    project_id, _ = _seed(sessions, tmp_path, tenant_id, "tenant-a")
    properties = [
        {"property": "properties/1", "displayName": "Acme A", "parent": "accounts/1"},
        {"property": "properties/2", "displayName": "Acme B", "parent": "accounts/1"},
    ]
    streams = {
        "properties/1": [_web_stream("properties/1", "https://acme.example")],
        "properties/2": [_web_stream("properties/2", "https://acme.example", "999")],
    }
    _fake_google(monkeypatch, properties, streams, REFERRALS, TOTALS)

    response = _callback(client, _authorize(client, headers, project_id))
    location = response.headers["location"]
    assert "ga4=choose" in location
    session_id = parse_qs(urlparse(location).fragment.split("?", 1)[-1])["ga4_session"][0]

    offered = client.get(
        f"/api/v1/projects/{project_id}/searchdata/ga4/session/{session_id}", headers=headers,
    )
    assert offered.status_code == 200
    assert {item["property"] for item in offered.json()["properties"]} == {"properties/1", "properties/2"}

    bad = client.post(f"/api/v1/projects/{project_id}/searchdata/ga4/select", headers=headers, json={
        "session_id": session_id, "property_id": "properties/9",
    })
    assert bad.status_code == 400

    chosen = client.post(f"/api/v1/projects/{project_id}/searchdata/ga4/select", headers=headers, json={
        "session_id": session_id, "property_id": "properties/1",
    })
    assert chosen.status_code == 200
    assert chosen.json()["property"] == "properties/1"

    reused = client.post(f"/api/v1/projects/{project_id}/searchdata/ga4/select", headers=headers, json={
        "session_id": session_id, "property_id": "properties/1",
    })
    assert reused.status_code == 410


def test_no_property_and_unconfigured_paths(ga4_client, monkeypatch):
    client, sessions, tmp_path = ga4_client
    tenant_id, _, headers = _register(client, "owner@acme.example", "tenant-a")
    project_id, _ = _seed(sessions, tmp_path, tenant_id, "tenant-a")
    _fake_google(monkeypatch, [{"property": "properties/9", "displayName": "Other", "parent": "accounts/1"}], {}, (), TOTALS)

    response = _callback(client, _authorize(client, headers, project_id))
    assert "ga4=no_property" in response.headers["location"]

    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID")
    assert client.post(
        f"/api/v1/projects/{project_id}/searchdata/ga4/authorize", headers=headers,
    ).status_code == 404
    status = client.get("/api/v1/searchdata/ga4/status", headers=headers)
    assert status.status_code == 200 and status.json()["configured"] is False


def test_tenant_isolation_viewer_role_and_delete(ga4_client, monkeypatch):
    client, sessions, tmp_path = ga4_client
    tenant_a, _, headers_a = _register(client, "owner@acme.example", "tenant-a")
    _, _, headers_b = _register(client, "owner@other.example", "tenant-b")
    project_id, root = _seed(sessions, tmp_path, tenant_a, "tenant-a")
    _fake_google(monkeypatch, PROPERTIES, STREAMS, REFERRALS, TOTALS)
    _callback(client, _authorize(client, headers_a, project_id))
    assert (root / "searchdata" / "ga4_snapshot.json").is_file()

    assert client.get(f"/api/v1/projects/{project_id}/searchdata/ga4", headers=headers_b).status_code == 404
    assert client.delete(f"/api/v1/projects/{project_id}/searchdata/ga4", headers=headers_b).status_code == 404
    assert client.post(f"/api/v1/projects/{project_id}/searchdata/ga4/authorize", headers=headers_b).status_code == 404

    with sessions() as db:
        membership = db.query(Membership).filter(Membership.tenant_id == tenant_a).first()
        membership.role = "viewer"
        db.commit()
    assert client.get(f"/api/v1/projects/{project_id}/searchdata/ga4", headers=headers_a).status_code == 200
    assert client.delete(f"/api/v1/projects/{project_id}/searchdata/ga4", headers=headers_a).status_code == 403
    with sessions() as db:
        membership = db.query(Membership).filter(Membership.tenant_id == tenant_a).first()
        membership.role = "owner"
        db.commit()

    deleted = client.delete(f"/api/v1/projects/{project_id}/searchdata/ga4", headers=headers_a)
    assert deleted.json() == {"ok": True, "deleted": True}


def test_callback_maps_google_errors(ga4_client, monkeypatch):
    client, sessions, tmp_path = ga4_client
    tenant_id, _, headers = _register(client, "owner@acme.example", "tenant-a")
    project_id, _ = _seed(sessions, tmp_path, tenant_id, "tenant-a")

    def fake_post(url, data=None, timeout=None):
        if url == oauth.GOOGLE_REVOKE_ENDPOINT:
            return FakeResponse(200, {})
        return FakeResponse(200, {"access_token": "ya29.ga4-secret", "scope": oauth.GA4_SCOPE})

    monkeypatch.setattr(oauth.requests, "post", fake_post)

    denied = _callback(client, _authorize(client, headers, project_id), error="access_denied", code="")
    assert "ga4=denied" in denied.headers["location"]

    scope = _callback(client, _authorize(client, headers, project_id), error="invalid_scope", code="")
    assert "ga4=scope_not_granted" in scope.headers["location"]

    for status_code, outcome in ((403, "permission_denied"), (429, "rate_limited")):
        monkeypatch.setattr(ga4.requests, "request", lambda *a, _code=status_code, **k: FakeResponse(_code, {}))
        response = _callback(client, _authorize(client, headers, project_id))
        assert f"ga4={outcome}" in response.headers["location"]


def test_authorize_rate_limit_fail_closed(ga4_client, monkeypatch):
    from api.rate_limit import RateLimitUnavailable
    from api.searchdata import router as searchdata_router

    client, sessions, tmp_path = ga4_client
    tenant_id, _, headers = _register(client, "owner@acme.example", "tenant-a")
    project_id, _ = _seed(sessions, tmp_path, tenant_id, "tenant-a")

    def unavailable(*args, **kwargs):
        raise RateLimitUnavailable("rate_limit_unavailable")

    monkeypatch.setattr(searchdata_router, "check_scope", unavailable)
    response = client.post(f"/api/v1/projects/{project_id}/searchdata/ga4/authorize", headers=headers)
    assert response.status_code == 503

    class Denied:
        allowed = False
        limit = 10
        remaining = 0
        reset_at = 0

    monkeypatch.setattr(searchdata_router, "check_scope", lambda *a, **k: Denied())
    response = client.post(f"/api/v1/projects/{project_id}/searchdata/ga4/authorize", headers=headers)
    assert response.status_code == 429


def test_key_events_not_configured_still_ready(ga4_client, monkeypatch):
    client, sessions, tmp_path = ga4_client
    tenant_id, _, headers = _register(client, "owner@acme.example", "tenant-a")
    project_id, _ = _seed(sessions, tmp_path, tenant_id, "tenant-a")
    _fake_google(monkeypatch, PROPERTIES, STREAMS, REFERRALS, TOTALS, key_events=())

    _callback(client, _authorize(client, headers, project_id))
    summary = client.get(f"/api/v1/projects/{project_id}/searchdata/ga4", headers=headers).json()
    assert summary["status"] == "ready"
    assert summary["key_events"]["status"] == "not_configured"
    assert summary["key_events"]["count"] == 0


def test_delete_ga4_keeps_gsc_snapshot(ga4_client, monkeypatch):
    client, sessions, tmp_path = ga4_client
    tenant_id, _, headers = _register(client, "owner@acme.example", "tenant-a")
    project_id, root = _seed(sessions, tmp_path, tenant_id, "tenant-a")
    (root / "searchdata").mkdir(parents=True, exist_ok=True)
    (root / "searchdata" / "gsc_snapshot.json").write_text(json.dumps({"schema_version": 1}), "utf-8")

    _fake_google(monkeypatch, PROPERTIES, STREAMS, REFERRALS, TOTALS)
    _callback(client, _authorize(client, headers, project_id))
    assert (root / "searchdata" / "ga4_snapshot.json").is_file()

    client.delete(f"/api/v1/projects/{project_id}/searchdata/ga4", headers=headers)
    assert (root / "searchdata" / "gsc_snapshot.json").is_file()
