import json
import logging
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.adapters import engine as engine_adapter
from api.db import Base, get_db
from api.main import app
from api.models import Job, Membership, Project, ProductEvent
from api.searchdata import candidates, gsc, oauth


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


def _rows(*items):
    return [{"query": q, "clicks": c, "impressions": i, "position": p} for q, c, i, p in items]


# ---------- 纯函数 ----------

def test_select_excludes_branded_and_short_queries_and_prefers_intent():
    rows = _rows(
        ("acme crm login", 50, 900, 1.2),
        ("acmehq pricing", 10, 300, 2.0),
        ("crm", 5, 5000, 30.0),
        ("crm for small teams", 3, 800, 12.0),
        ("best crm for startups", 2, 400, 9.4),
        ("how to choose a crm", 1, 200, 15.0),
        ("customer database spreadsheet", 0, 1200, 25.0),
    )
    selected, excluded = candidates.select(rows, CONFIG)

    queries = [item["query"] for item in selected]
    assert excluded == {"branded": 2, "too_short": 1}
    # 意图词优先（展示量降序），无意图词的排在后面。
    assert queries == ["best crm for startups", "how to choose a crm", "customer database spreadsheet", "crm for small teams"]
    assert selected[1]["prompt"] == "How to choose a crm?"
    assert selected[0]["prompt"] == "What are the best crm for startups?"
    assert all(item["id"].startswith("gsc-") for item in selected)


def test_select_caps_candidates_and_handles_cjk():
    rows = _rows(*[(f"crm tool option {n}", 0, 1000 - n, 10.0) for n in range(30)], ("客户管理软件推荐", 1, 50, 8.0), ("软件", 0, 9999, 40.0))
    selected, excluded = candidates.select(rows, CONFIG)

    assert len(selected) == candidates.MAX_CANDIDATES
    assert excluded["too_short"] == 1
    cjk = candidates.select(_rows(("客户管理软件推荐", 1, 50, 8.0)), CONFIG)[0][0]
    assert cjk["market"] == "cn"
    assert "客户管理软件推荐" in cjk["prompt"]


def test_anonymous_click_share_handles_zero_and_overcount():
    rows = _rows(("a b", 30, 100, 1.0), ("c d", 40, 100, 1.0))
    assert candidates.anonymous_click_share({"clicks": 100}, rows) == 0.3
    assert candidates.anonymous_click_share({"clicks": 0}, rows) is None
    assert candidates.anonymous_click_share({"clicks": 50}, rows) == 0.0


def test_snapshot_flags_low_volume_and_keeps_limited_rows():
    fetched = {
        "window": {"start": "2026-07-29", "end": "2026-10-26"},
        "rows": _rows(*[(f"query term {n}", 0, n, 20.0) for n in range(300)]),
        "totals": {"clicks": 0, "impressions": 500},
    }
    snapshot = candidates.build_snapshot("sc-domain:acme.example", fetched, CONFIG)
    assert snapshot["low_volume"] is False
    assert len(snapshot["rows"]) == candidates.KEEP_ROWS
    assert snapshot["rows"][0]["impressions"] == 299
    assert snapshot["anonymous_click_share"] is None

    empty = candidates.build_snapshot("sc-domain:acme.example", {**fetched, "rows": []}, CONFIG)
    assert empty["candidates"] == [] and empty["low_volume"] is True


@pytest.mark.parametrize("project_url, sites, expected", [
    ("https://acme.example", [
        {"site_url": "https://acme.example/", "permission": "siteOwner"},
        {"site_url": "sc-domain:acme.example", "permission": "siteFullUser"},
        {"site_url": "https://other.example/", "permission": "siteOwner"},
    ], ["sc-domain:acme.example", "https://acme.example/"]),
    ("https://www.acme.example/pricing", [
        {"site_url": "https://www.acme.example/", "permission": "siteOwner"},
    ], ["https://www.acme.example/"]),
    ("https://acme.example", [{"site_url": "https://other.example/", "permission": "siteOwner"}], []),
])
def test_match_sites_orders_domain_property_first(project_url, sites, expected):
    assert [item["site_url"] for item in gsc.match_sites(project_url, sites)] == expected


def test_list_sites_drops_unverified_and_maps_errors(monkeypatch):
    monkeypatch.setattr(gsc.requests, "request", lambda *a, **k: FakeResponse(200, {"siteEntry": [
        {"siteUrl": "sc-domain:acme.example", "permissionLevel": "siteOwner"},
        {"siteUrl": "https://acme.example/", "permissionLevel": "siteUnverifiedUser"},
    ]}))
    assert gsc.list_sites("token") == [{"site_url": "sc-domain:acme.example", "permission": "siteOwner"}]

    for code, error in ((403, "gsc_permission_denied"), (429, "gsc_rate_limited"), (500, "gsc_upstream_error")):
        monkeypatch.setattr(gsc.requests, "request", lambda *a, _c=code, **k: FakeResponse(_c, {}))
        with pytest.raises(gsc.GscError, match=error):
            gsc.list_sites("token")


def test_fetch_queries_uses_final_window_and_single_dimension(monkeypatch):
    calls = []

    def fake_request(method, url, headers=None, json=None, timeout=None):
        calls.append((method, url, json))
        if json.get("dimensions"):
            return FakeResponse(200, {"rows": [{"keys": ["best crm"], "clicks": 2, "impressions": 90, "position": 7.26}]})
        return FakeResponse(200, {"rows": [{"clicks": 5, "impressions": 140}]})

    monkeypatch.setattr(gsc.requests, "request", fake_request)
    result = gsc.fetch_queries("token", "sc-domain:acme.example", today=date(2026, 10, 29))

    assert result["window"] == {"start": "2026-07-29", "end": "2026-10-26"}
    assert result["rows"] == [{"query": "best crm", "clicks": 2, "impressions": 90, "position": 7.3}]
    assert result["totals"] == {"clicks": 5, "impressions": 140}
    assert "sc-domain%3Aacme.example" in calls[0][1]
    assert calls[0][2]["dataState"] == "final" and calls[0][2]["type"] == "web"
    assert "dimensions" not in calls[1][2]


# ---------- OAuth ----------

def test_state_is_signed_bound_and_single_use(monkeypatch, project_lock_redis):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")

    url = oauth.authorization_url(7, 3, 11)
    query = parse_qs(urlparse(url).query)
    assert query["scope"] == [oauth.SCOPE]
    assert query["code_challenge_method"] == ["S256"]
    assert "access_type" not in query
    user_id, tenant_id, project_id, nonce = oauth.verify_state(query["state"][0])
    assert (user_id, tenant_id, project_id) == (7, 3, 11)

    with pytest.raises(oauth.OAuthError, match="gsc_state_invalid"):
        oauth.verify_state(query["state"][0] + "x")
    from api.auth.security import create_access_token
    with pytest.raises(oauth.OAuthError, match="gsc_state_invalid"):
        oauth.verify_state(create_access_token(7, 3))

    posted = {}

    def fake_post(url, data=None, timeout=None):
        posted.update(data)
        return FakeResponse(200, {"access_token": "ya29.secret", "scope": oauth.SCOPE})

    monkeypatch.setattr(oauth.requests, "post", fake_post)
    assert oauth.exchange_code("auth-code", nonce) == "ya29.secret"
    assert posted["code_verifier"]
    with pytest.raises(oauth.OAuthError, match="gsc_state_invalid"):
        oauth.exchange_code("auth-code", nonce)


def test_exchange_rejects_missing_scope_and_revokes(monkeypatch, project_lock_redis):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    query = parse_qs(urlparse(oauth.authorization_url(1, 1, 1)).query)
    nonce = oauth.verify_state(query["state"][0])[3]
    revoked = []

    def fake_post(url, data=None, timeout=None):
        if url == oauth.GOOGLE_REVOKE_ENDPOINT:
            revoked.append(data["token"])
            return FakeResponse(200, {})
        return FakeResponse(200, {"access_token": "ya29.partial", "scope": "openid"})

    monkeypatch.setattr(oauth.requests, "post", fake_post)
    with pytest.raises(oauth.OAuthError, match="gsc_scope_not_granted"):
        oauth.exchange_code("code", nonce)
    assert revoked == ["ya29.partial"]


# ---------- API 流程 ----------

@pytest.fixture()
def gsc_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://citeaura.test")
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    engine = create_engine(f"sqlite:///{tmp_path / 'gsc.sqlite'}")
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


def _fake_google(monkeypatch, sites, rows, totals=None, token="ya29.flow-secret"):
    revoked = []

    def fake_post(url, data=None, timeout=None):
        if url == oauth.GOOGLE_REVOKE_ENDPOINT:
            revoked.append(data["token"])
            return FakeResponse(200, {})
        return FakeResponse(200, {"access_token": token, "scope": oauth.SCOPE})

    def fake_request(method, url, headers=None, json=None, timeout=None):
        assert headers["Authorization"] == f"Bearer {token}"
        if url.endswith("/sites"):
            return FakeResponse(200, {"siteEntry": sites})
        if json.get("dimensions"):
            return FakeResponse(200, {"rows": [
                {"keys": [q], "clicks": c, "impressions": i, "position": p} for q, c, i, p in rows
            ]})
        return FakeResponse(200, {"rows": [totals or {"clicks": 10, "impressions": 3000}]})

    monkeypatch.setattr(oauth.requests, "post", fake_post)
    monkeypatch.setattr(gsc.requests, "request", fake_request)
    return revoked


def _authorize(client, headers, project_id):
    response = client.post(f"/api/v1/projects/{project_id}/searchdata/gsc/authorize", headers=headers)
    assert response.status_code == 200, response.text
    return parse_qs(urlparse(response.json()["authorization_url"]).query)["state"][0]


def _callback(client, state, **params):
    return client.get("/api/v1/searchdata/gsc/callback", params={"state": state, "code": "auth-code", **params}, follow_redirects=False)


ROWS = (
    ("acme crm login", 9, 900, 1.1),
    ("best crm for startups", 2, 400, 9.4),
    ("how to choose a crm", 1, 300, 15.0),
)


def test_single_match_fetches_snapshot_adds_questions_and_never_stores_token(gsc_client, monkeypatch, caplog):
    client, sessions, tmp_path = gsc_client
    tenant_id, _, headers = _register(client, "owner@acme.example", "tenant-a")
    project_id, root = _seed(sessions, tmp_path, tenant_id, "tenant-a")
    revoked = _fake_google(monkeypatch, [{"siteUrl": "sc-domain:acme.example", "permissionLevel": "siteOwner"}], ROWS)

    assert client.get(f"/api/v1/projects/{project_id}/searchdata/gsc", headers=headers).json()["status"] == "not_connected"
    with caplog.at_level(logging.DEBUG):
        response = _callback(client, _authorize(client, headers, project_id))
    assert response.status_code == 303
    assert response.headers["location"] == f"https://citeaura.test/app/#/questions?gsc=ready&project={project_id}"
    assert revoked == ["ya29.flow-secret"]

    summary = client.get(f"/api/v1/projects/{project_id}/searchdata/gsc", headers=headers).json()
    assert summary["status"] == "ready"
    assert summary["source_label"] == "GSC·第一方"
    assert summary["property"] == "sc-domain:acme.example"
    # 总点击 10，三条查询共 12 次点击：超出部分截到 0。
    assert summary["anonymous_click_share"] == 0.0
    assert [item["query"] for item in summary["candidates"]] == ["best crm for startups", "how to choose a crm"]

    candidate = summary["candidates"][0]
    forged = client.post(f"/api/v1/projects/{project_id}/searchdata/gsc/questions", headers=headers, json={
        "items": [{"id": "gsc-forged", "text": "Anything"}],
    })
    assert forged.status_code == 400 and forged.json()["error"] == "gsc_candidate_not_found"
    added = client.post(f"/api/v1/projects/{project_id}/searchdata/gsc/questions", headers=headers, json={
        "items": [{"id": candidate["id"], "text": "Which CRM is best for an early-stage startup?", "gsc": {"impressions": 999999}}],
    })
    assert added.status_code == 200 and added.json()["added"] == 1
    again = client.post(f"/api/v1/projects/{project_id}/searchdata/gsc/questions", headers=headers, json={
        "items": [{"id": candidate["id"], "text": "Which CRM is best for an early-stage startup?"}],
    })
    assert again.json()["added"] == 0
    refreshed = client.get(f"/api/v1/projects/{project_id}/searchdata/gsc", headers=headers).json()
    # 用户改写过的问题也要标为已入库，避免重复加入。
    assert refreshed["candidates"][0]["in_question_bank"] is True
    assert refreshed["candidates"][1]["in_question_bank"] is False

    question = json.loads((root / "geo.json").read_text("utf-8"))["questions"][0]
    assert question["source"] == "gsc"
    assert question["gsc"]["impressions"] == 400
    assert question["gsc"]["query"] == "best crm for startups"

    stored = "".join(path.read_text("utf-8") for path in (tmp_path / "work").rglob("*") if path.is_file())
    assert "ya29.flow-secret" not in stored
    assert "ya29.flow-secret" not in caplog.text
    with sessions() as db:
        names = [event.name for event in db.query(ProductEvent).all()]
        assert {"gsc_connect_started", "gsc_connect_completed", "gsc_candidates_shown", "gsc_questions_added"} <= set(names)
        assert all("best crm" not in (event.properties or "") for event in db.query(ProductEvent).all())


def test_multiple_matches_require_choice_from_offered_properties(gsc_client, monkeypatch):
    client, sessions, tmp_path = gsc_client
    tenant_id, _, headers = _register(client, "owner@acme.example", "tenant-a")
    project_id, _ = _seed(sessions, tmp_path, tenant_id, "tenant-a")
    revoked = _fake_google(monkeypatch, [
        {"siteUrl": "https://acme.example/", "permissionLevel": "siteOwner"},
        {"siteUrl": "sc-domain:acme.example", "permissionLevel": "siteFullUser"},
    ], ROWS)

    location = _callback(client, _authorize(client, headers, project_id)).headers["location"]
    params = parse_qs(location.split("?", 1)[1])
    assert params["gsc"] == ["choose"]
    session_id = params["gsc_session"][0]
    offered = client.get(f"/api/v1/projects/{project_id}/searchdata/gsc/session/{session_id}", headers=headers).json()
    assert offered["properties"] == ["sc-domain:acme.example", "https://acme.example/"]

    bad = client.post(f"/api/v1/projects/{project_id}/searchdata/gsc/select", headers=headers, json={
        "session_id": session_id, "site_url": "https://evil.example/",
    })
    assert bad.status_code == 400
    chosen = client.post(f"/api/v1/projects/{project_id}/searchdata/gsc/select", headers=headers, json={
        "session_id": session_id, "site_url": "https://acme.example/",
    })
    assert chosen.status_code == 200 and chosen.json()["property"] == "https://acme.example/"
    assert revoked == ["ya29.flow-secret"]
    reused = client.post(f"/api/v1/projects/{project_id}/searchdata/gsc/select", headers=headers, json={
        "session_id": session_id, "site_url": "https://acme.example/",
    })
    assert reused.status_code == 410


def test_callback_rejects_denied_tampered_and_downgraded_users(gsc_client, monkeypatch):
    client, sessions, tmp_path = gsc_client
    tenant_id, user_id, headers = _register(client, "owner@acme.example", "tenant-a")
    project_id, _ = _seed(sessions, tmp_path, tenant_id, "tenant-a")
    _fake_google(monkeypatch, [], ())

    assert "gsc=state_invalid" in _callback(client, "not-a-token").headers["location"]
    assert "gsc=denied" in client.get("/api/v1/searchdata/gsc/callback", params={
        "state": _authorize(client, headers, project_id), "error": "access_denied",
    }, follow_redirects=False).headers["location"]

    state = _authorize(client, headers, project_id)
    with sessions() as db:
        db.get(Membership, {"tenant_id": tenant_id, "user_id": user_id}).role = "viewer"
        db.commit()
    assert "gsc=state_invalid" in _callback(client, state).headers["location"]


def test_no_property_and_unconfigured_paths(gsc_client, monkeypatch):
    client, sessions, tmp_path = gsc_client
    tenant_id, _, headers = _register(client, "owner@acme.example", "tenant-a")
    project_id, _ = _seed(sessions, tmp_path, tenant_id, "tenant-a")
    revoked = _fake_google(monkeypatch, [], ())
    assert "gsc=no_property" in _callback(client, _authorize(client, headers, project_id)).headers["location"]
    assert revoked == ["ya29.flow-secret"]

    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID")
    response = client.post(f"/api/v1/projects/{project_id}/searchdata/gsc/authorize", headers=headers)
    assert response.status_code == 404 and response.json()["error"] == "gsc_not_configured"
    assert client.get(f"/api/v1/projects/{project_id}/searchdata/gsc", headers=headers).json()["configured"] is False


def test_tenant_isolation_viewer_role_and_delete(gsc_client, monkeypatch):
    client, sessions, tmp_path = gsc_client
    tenant_a, _, headers_a = _register(client, "owner@acme.example", "tenant-a")
    _, _, headers_b = _register(client, "owner@other.example", "tenant-b")
    project_id, root = _seed(sessions, tmp_path, tenant_a, "tenant-a")
    _fake_google(monkeypatch, [{"siteUrl": "sc-domain:acme.example", "permissionLevel": "siteOwner"}], ROWS)
    _callback(client, _authorize(client, headers_a, project_id))
    assert (root / "searchdata" / "gsc_snapshot.json").is_file()

    assert client.get(f"/api/v1/projects/{project_id}/searchdata/gsc", headers=headers_b).status_code == 404
    assert client.delete(f"/api/v1/projects/{project_id}/searchdata/gsc", headers=headers_b).status_code == 404
    assert client.post(f"/api/v1/projects/{project_id}/searchdata/gsc/authorize", headers=headers_b).status_code == 404

    with sessions() as db:
        membership = db.query(Membership).filter(Membership.tenant_id == tenant_a).first()
        membership.role = "viewer"
        db.commit()
    assert client.delete(f"/api/v1/projects/{project_id}/searchdata/gsc", headers=headers_a).status_code == 403
    with sessions() as db:
        membership = db.query(Membership).filter(Membership.tenant_id == tenant_a).first()
        membership.role = "owner"
        db.commit()

    deleted = client.delete(f"/api/v1/projects/{project_id}/searchdata/gsc", headers=headers_a)
    assert deleted.json() == {"ok": True, "deleted": True}
    assert not (root / "searchdata").exists()


def test_refetch_rotates_history_and_questions_wait_for_idle_project(gsc_client, monkeypatch):
    client, sessions, tmp_path = gsc_client
    tenant_id, _, headers = _register(client, "owner@acme.example", "tenant-a")
    project_id, root = _seed(sessions, tmp_path, tenant_id, "tenant-a")
    _fake_google(monkeypatch, [{"siteUrl": "sc-domain:acme.example", "permissionLevel": "siteOwner"}], ROWS)
    _callback(client, _authorize(client, headers, project_id))
    _callback(client, _authorize(client, headers, project_id))
    assert len(list((root / "searchdata" / "history").glob("gsc_snapshot-*.json"))) == 1

    candidate = client.get(f"/api/v1/projects/{project_id}/searchdata/gsc", headers=headers).json()["candidates"][0]
    with sessions() as db:
        db.add(Job(project_id=project_id, action="sample", status="running"))
        db.commit()
    busy = client.post(f"/api/v1/projects/{project_id}/searchdata/gsc/questions", headers=headers, json={"items": [{"id": candidate["id"]}]})
    assert busy.status_code == 409


def test_demand_pairs_google_figures_with_latest_sampling(gsc_client, monkeypatch):
    client, sessions, tmp_path = gsc_client
    tenant_id, _, headers = _register(client, "owner@acme.example", "tenant-a")
    project_id, root = _seed(sessions, tmp_path, tenant_id, "tenant-a")
    assert client.get(f"/api/v1/projects/{project_id}/searchdata/gsc/demand", headers=headers).json()["status"] == "no_gsc_questions"

    _fake_google(monkeypatch, [{"siteUrl": "sc-domain:acme.example", "permissionLevel": "siteOwner"}], ROWS)
    _callback(client, _authorize(client, headers, project_id))
    summary = client.get(f"/api/v1/projects/{project_id}/searchdata/gsc", headers=headers).json()
    ids = [item["id"] for item in summary["candidates"]]
    client.post(f"/api/v1/projects/{project_id}/searchdata/gsc/questions", headers=headers, json={"items": [{"id": value} for value in ids]})

    pending = client.get(f"/api/v1/projects/{project_id}/searchdata/gsc/demand", headers=headers).json()
    assert pending["status"] == "awaiting_sample"
    assert pending["summary"] == {"questions": 2, "measured": 0, "mentioned": 0}
    assert pending["items"][0]["google"]["impressions"] == 400
    assert pending["items"][0]["google"]["source_label"] == "GSC·第一方"

    config = json.loads((root / "geo.json").read_text("utf-8"))
    from api.adapters import brand_identity
    version = brand_identity.question_set_version(config)["version"]
    first = config["questions"][0]
    (root / "samples").mkdir()
    (root / "samples" / "2026-10-29.jsonl").write_text(json.dumps({
        "platform": "openai", "question_id": first["id"], "question": first["text"], "ok": True,
        "market": "global", "terminal": "api", "sample_mode": "api", "search_enabled": False,
        "ts": "2026-10-29T10:00:00+00:00", "question_set_version": version,
        "analysis": {"brand_mentioned": False, "competitors_mentioned": ["Rival CRM"]},
    }) + "\n", "utf-8")

    measured = client.get(f"/api/v1/projects/{project_id}/searchdata/gsc/demand", headers=headers).json()
    assert measured["status"] == "measured"
    assert measured["summary"] == {"questions": 2, "measured": 1, "mentioned": 0}
    engine = measured["items"][0]["engines"][0]
    assert engine["competitors"] == ["Rival CRM"]
    assert engine["sampling_mode_code"] == "parametric"
    assert engine["sampling_mode"] == "API·参数化知识"
