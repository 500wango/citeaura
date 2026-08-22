import json
import sys
import types

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.db import Base, get_db
from api.main import app
from api.models import Job
from api.projects import router as project_router


def test_prompt_research_generates_fanout_and_persists_file(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    monkeypatch.setattr(project_router, "validate_outbound_url", lambda value, **kwargs: value)
    monkeypatch.setattr(project_router.task_bootstrap, "delay", lambda *a, **kw: types.SimpleNamespace(id="boot"))
    monkeypatch.setattr("api.adapters.engine.WORK_ROOT", tmp_path / "work")

    def fake_init(args):
        from api.adapters.engine import geolib

        directory = geolib.project_dir(args.slug)
        directory.mkdir(parents=True, exist_ok=True)
        geolib.write_json(directory / "geo.json", {
            "brand": {"name": "Research Brand", "site": args.url, "industry": "AI visibility"},
            "market": "global",
            "questions": [],
            "competitors": [],
        })

    monkeypatch.setitem(sys.modules, "geo", types.SimpleNamespace(cmd_init=fake_init))
    engine = create_engine(f"sqlite:///{tmp_path / 'research.sqlite'}")
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
        registered = client.post("/api/v1/auth/register", json={"email": "research@example.com", "password": "correct-horse-battery"})
        assert registered.status_code == 201
        token = client.post("/api/v1/auth/login", json={"email": "research@example.com", "password": "correct-horse-battery"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        created = client.post("/api/v1/projects", headers=headers, json={"url": "https://research.example"})
        assert created.status_code == 202
        with sessions() as db:
            db.query(Job).filter(Job.id == created.json()["job_id"]).update({"status": "done"})
            db.commit()
        response = client.post(
            f"/api/v1/projects/{created.json()['project_id']}/prompt-research",
            headers=headers,
            json={"seeds": ["AI visibility platform"]},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["candidate_count"] >= 12
        assert len(body["fanout"][0]["queries"]) == 6
        assert client.get(f"/api/v1/projects/{created.json()['project_id']}/prompt-research", headers=headers).json()["candidate_count"] >= 12
        project_slug = created.json()["slug"]
        path = next((tmp_path / "work").glob(f"*/{project_slug}/prompt_research.json"))
        assert json.loads(path.read_text())["seeds"]
    app.dependency_overrides.clear()
