from fastapi.testclient import TestClient

from api.main import app


def test_ui_is_served_with_disvorai_brand_and_saas_adapter():
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert "DisvorAI" in response.text
    assert "GeoLook" not in response.text
    assert 'Geo<span style="color:var(--accent)">Look</span>' not in response.text
    assert "/api/v1/auth/login" in response.text
    assert "/api/v1/projects" in response.text
    assert "/api/v1/settings/keys" in response.text
    assert "disvorai_access_token" in response.text
