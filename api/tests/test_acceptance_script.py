from scripts.acceptance import collect_checks


class Response:
    def __init__(self, status_code=200, text="", body=None):
        self.status_code = status_code
        self.text = text
        self._body = body or {}

    def json(self):
        return self._body


def test_acceptance_script_checks_public_surface(monkeypatch):
    html = "DisvorAI API·参数化 API·联网 人工·网页端 /app"

    def fake_get(_url, timeout):
        if _url.endswith("/api/v1/health"):
            return Response(body={"status": "ok"})
        return Response(text=html)

    monkeypatch.setattr("scripts.acceptance.requests.get", fake_get)
    result = collect_checks("http://example.test")

    assert result
    assert all(item["passed"] for item in result)


def test_acceptance_script_fails_when_server_is_unreachable(monkeypatch):
    def fail_get(_url, timeout):
        raise OSError("offline")

    monkeypatch.setattr("scripts.acceptance.requests.get", fail_get)
    result = collect_checks("http://example.test")

    assert result[-1] == {"name": "http", "passed": False, "detail": "OSError"}
