import io
import zipfile

from scripts.workflow_acceptance import AcceptanceError, _delivery_contract, run_workflow


class Response:
    def __init__(self, status_code=200, body=None, content=b""):
        self.status_code = status_code
        self._body = body or {}
        self.content = content

    def json(self):
        return self._body


class Session:
    def __init__(self, failed_job=False):
        self.headers = {}
        self.failed_job = failed_job

    def request(self, method, url, timeout, **kwargs):
        path = "/" + url.split("/", 3)[-1]
        if path == "/api/v1/auth/login":
            return Response(body={"access_token": "secret-token"})
        if path == "/api/v1/me":
            return Response(body={"email": "acceptance@example.com"})
        if path == "/api/v1/projects" and method == "GET":
            return Response(body={"projects": []})
        if path == "/api/v1/projects" and method == "POST":
            return Response(202, {"project_id": 7, "job_id": 11, "status": "bootstrapping"})
        if path.startswith("/api/v1/projects/7/jobs/"):
            status = "failed" if self.failed_job else "done"
            return Response(body={"job": {"status": status, "action": "pipeline", "error": "boom" if self.failed_job else None}})
        if path == "/api/v1/projects/7/report":
            return Response(body={"date": "2026-08-01", "report": {"sample_count": 2}})
        if path == "/api/v1/projects/7/engines":
            return Response(body={"engines": [{"sampling_mode": "API - Parametric knowledge"}]})
        if path == "/api/v1/projects/7/samples/2026-08-01":
            return Response(body={"samples": [{"answer": "raw"}]})
        if path == "/api/v1/projects/7/tickets":
            return Response(body={"tickets": [{"id": "T-001"}]})
        if path == "/api/v1/projects/7/verify" and method == "POST":
            return Response(202, {"job_id": 12})
        if path == "/api/v1/projects/7/verify/history":
            return Response(body={"history": [{"changed": 1}]})
        if path == "/api/v1/projects/7/deliver" and method == "POST":
            return Response(202, {"job_id": 13})
        if path == "/api/v1/projects/7/deliveries":
            package = {
                "date": "2026-08-01", "readiness": "review_required",
                "asset_summary": {"ready": 1, "needs_review": 0, "template": 1},
            }
            return Response(body={"deliveries": ["2026-08-01"], "packages": [package]})
        if path == "/api/v1/projects/7/deliveries/2026-08-01":
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w") as bundle:
                bundle.writestr("index.html", "delivery")
                for stem in (
                    "01-Audit-Report",
                    "02-Execution-Plan",
                    "03-Ticket-Log",
                    "04-Acceptance-Checklist",
                    "05-Draft-Risks",
                    "06-Build-Map",
                ):
                    bundle.writestr(f"{stem}.md", stem)
                bundle.writestr("03-Ticket-Log.csv", "ID,Priority\n")
                bundle.writestr("assets/index.json", "{}")
            return Response(content=output.getvalue())
        return Response(404, {"error": "not_found"})


def test_workflow_acceptance_covers_report_verify_and_delivery():
    session = Session()
    checks = run_workflow(
        "https://app.example.test",
        "acceptance@example.com",
        "password",
        "https://brand.example",
        session=session,
        sleep=lambda _seconds: None,
    )

    assert all(item["passed"] for item in checks)
    assert {item["name"] for item in checks} == {
        "authentication", "domain_onboarding", "initial_pipeline", "visibility_report",
        "tickets", "verification", "delivery",
    }
    assert session.headers == {"Authorization": "Bearer secret-token"}


def test_workflow_acceptance_reports_failed_worker_job_without_secrets():
    checks = run_workflow(
        "https://app.example.test",
        "acceptance@example.com",
        "password-not-in-output",
        "https://brand.example",
        session=Session(failed_job=True),
        sleep=lambda _seconds: None,
    )

    assert checks[-1]["passed"] is False
    assert "job_failed" in checks[-1]["detail"]
    assert "password-not-in-output" not in str(checks)


def test_delivery_contract_rejects_legacy_document_names():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr("index.html", "delivery")
        for name in ("01-Diagnostic", "02-Strategy", "03-Tickets", "04-Verification", "05-Draft-Risks", "06-Blueprint"):
            bundle.writestr(f"{name}.md", name)
        bundle.writestr("03-Ticket-Log.csv", "ID,Priority\n")
        bundle.writestr("assets/index.json", "{}")

    try:
        _delivery_contract(output.getvalue())
    except AcceptanceError as exc:
        assert "01-Audit-Report" in str(exc)
    else:
        raise AssertionError("legacy delivery names must fail the formal contract")
