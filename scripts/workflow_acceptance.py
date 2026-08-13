#!/usr/bin/env python3
"""执行需要真实账号、引擎 Key 和 Worker 的完整产品闭环验收。"""

import argparse
import io
import json
import os
import sys
import time
import zipfile
from urllib.parse import urljoin

import requests


TERMINAL_JOB_STATUSES = frozenset(("done", "failed", "stopped", "interrupted"))
SAMPLING_MODES = frozenset(("API - Parametric knowledge", "API - Search grounded", "Manual - Product interface"))


class AcceptanceError(RuntimeError):
    pass


def _url(base_url, path):
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def _json(response):
    try:
        return response.json()
    except ValueError as exc:
        raise AcceptanceError(f"invalid_json:{response.status_code}") from exc


def _request(session, method, base_url, path, expected=(200,), **kwargs):
    try:
        response = session.request(method, _url(base_url, path), timeout=30, **kwargs)
    except requests.RequestException as exc:
        raise AcceptanceError(f"request_failed:{path}:{type(exc).__name__}") from exc
    if response.status_code not in expected:
        body = _json(response)
        error = body.get("error") or body.get("detail") or response.status_code
        raise AcceptanceError(f"request_rejected:{path}:{error}")
    return response


def _poll_job(session, base_url, project_id, job_id, timeout, poll_interval, sleep):
    if not job_id:
        raise AcceptanceError("job_id_missing")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = _request(
            session,
            "GET",
            base_url,
            f"/api/v1/projects/{project_id}/jobs/{job_id}",
        )
        job = _json(response).get("job") or {}
        state = job.get("status")
        if state in TERMINAL_JOB_STATUSES:
            if state != "done":
                raise AcceptanceError(f"job_{state}:{job.get('action') or job_id}:{job.get('error') or ''}")
            return job
        sleep(poll_interval)
    raise AcceptanceError(f"job_timeout:{job_id}")


def _delivery_contract(content):
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as bundle:
            names = bundle.namelist()
    except zipfile.BadZipFile as exc:
        raise AcceptanceError("delivery_zip_invalid") from exc
    missing = [number for number in ("01", "02", "03", "04", "05", "06") if not any(
        name.startswith(f"{number}-") for name in names
    )]
    if missing or "index.html" not in names or not any(name.startswith("assets/") for name in names):
        detail = ",".join(missing) if missing else "index_or_assets"
        raise AcceptanceError(f"delivery_contract_incomplete:{detail}")
    return names


def _existing_project(session, base_url, project_url):
    projects = _json(_request(session, "GET", base_url, "/api/v1/projects")).get("projects") or []
    target = project_url.rstrip("/").lower()
    return next((item for item in projects if str(item.get("url") or "").rstrip("/").lower() == target), None)


def run_workflow(
    base_url,
    email,
    password,
    project_url,
    market="both",
    timeout=1800,
    poll_interval=2,
    reuse_existing=False,
    session=None,
    sleep=time.sleep,
):
    """运行 PRD 的建项、报告、验收和交付闭环。"""
    checks = []

    def passed(name, detail):
        checks.append({"name": name, "passed": True, "detail": detail})

    session = session or requests.Session()
    try:
        login = _json(_request(
            session,
            "POST",
            base_url,
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        ))
        token = login.get("access_token")
        if not token:
            raise AcceptanceError("login_token_missing")
        session.headers.update({"Authorization": f"Bearer {token}"})
        me = _json(_request(session, "GET", base_url, "/api/v1/me"))
        if str(me.get("email") or "").lower() != email.lower():
            raise AcceptanceError("authenticated_user_mismatch")
        passed("authentication", "authenticated")

        project = _existing_project(session, base_url, project_url) if reuse_existing else None
        if project is None:
            created_at = time.monotonic()
            created = _json(_request(
                session,
                "POST",
                base_url,
                "/api/v1/projects",
                expected=(202,),
                json={"url": project_url, "market": market},
            ))
            project_id = created.get("project_id")
            job_id = created.get("job_id")
            if not project_id or not job_id:
                raise AcceptanceError("project_job_missing")
            elapsed = time.monotonic() - created_at
            if elapsed > 180 or created.get("status") not in ("initializing", "bootstrapping", "processing", "sampling"):
                raise AcceptanceError("domain_onboarding_slow_or_invalid")
            passed("domain_onboarding", f"{elapsed:.2f}s to {created.get('status')}")
        else:
            project_id = project.get("id")
            queued = _json(_request(
                session,
                "POST",
                base_url,
                f"/api/v1/projects/{project_id}/actions/serve",
                expected=(202,),
                json={"params": {}},
            ))
            job_id = queued.get("job_id")
            if not job_id:
                raise AcceptanceError("cycle_job_missing")
            passed("domain_onboarding", "reused")
        _poll_job(session, base_url, project_id, job_id, timeout, poll_interval, sleep)
        passed("initial_pipeline", "done")

        report = _json(_request(session, "GET", base_url, f"/api/v1/projects/{project_id}/report"))
        report_date = report.get("date")
        if not report_date or not isinstance(report.get("report"), dict):
            raise AcceptanceError("visibility_report_missing")
        engines = _json(_request(session, "GET", base_url, f"/api/v1/projects/{project_id}/engines")).get("engines") or []
        if not engines or any(item.get("sampling_mode") not in SAMPLING_MODES for item in engines):
            raise AcceptanceError("engine_sampling_modes_missing")
        samples = _json(_request(
            session,
            "GET",
            base_url,
            f"/api/v1/projects/{project_id}/samples/{report_date}",
        )).get("samples") or []
        if not samples:
            raise AcceptanceError("raw_samples_missing")
        passed("visibility_report", f"{len(engines)} engines, {len(samples)} samples")

        tickets = _json(_request(session, "GET", base_url, f"/api/v1/projects/{project_id}/tickets")).get("tickets") or []
        if not tickets:
            raise AcceptanceError("tickets_missing")
        passed("tickets", len(tickets))

        verify = _json(_request(
            session,
            "POST",
            base_url,
            f"/api/v1/projects/{project_id}/verify",
            expected=(202,),
        ))
        _poll_job(session, base_url, project_id, verify.get("job_id"), timeout, poll_interval, sleep)
        history = _json(_request(
            session,
            "GET",
            base_url,
            f"/api/v1/projects/{project_id}/verify/history",
        )).get("history") or []
        if not history:
            raise AcceptanceError("verification_history_missing")
        passed("verification", len(history))

        delivery = _json(_request(
            session,
            "POST",
            base_url,
            f"/api/v1/projects/{project_id}/deliver",
            expected=(202,),
        ))
        _poll_job(session, base_url, project_id, delivery.get("job_id"), timeout, poll_interval, sleep)
        deliveries = _json(_request(
            session,
            "GET",
            base_url,
            f"/api/v1/projects/{project_id}/deliveries",
        )).get("deliveries") or []
        if not deliveries:
            raise AcceptanceError("delivery_missing")
        latest = deliveries[0] if isinstance(deliveries[0], dict) else {"date": deliveries[0]}
        delivery_date = latest.get("date")
        if not delivery_date:
            raise AcceptanceError("delivery_date_missing")
        archive = _request(
            session,
            "GET",
            base_url,
            f"/api/v1/projects/{project_id}/deliveries/{delivery_date}",
        )
        names = _delivery_contract(archive.content)
        passed("delivery", f"{len(names)} files")
    except (AcceptanceError, OSError, ValueError) as exc:
        checks.append({"name": "workflow", "passed": False, "detail": str(exc)})
    return checks


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--email", default=os.getenv("ACCEPTANCE_EMAIL"))
    parser.add_argument("--project-url", default=os.getenv("ACCEPTANCE_PROJECT_URL"))
    parser.add_argument("--market", choices=("cn", "global", "both"), default="both")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--poll-interval", type=float, default=2)
    parser.add_argument("--reuse-existing", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    password = os.getenv("ACCEPTANCE_PASSWORD")
    if not args.email or not password or not args.project_url:
        print("ACCEPTANCE_EMAIL, ACCEPTANCE_PASSWORD and ACCEPTANCE_PROJECT_URL are required.", file=sys.stderr)
        return 2
    checks = run_workflow(
        args.base_url,
        args.email,
        password,
        args.project_url,
        market=args.market,
        timeout=max(1, args.timeout),
        poll_interval=max(0.1, args.poll_interval),
        reuse_existing=args.reuse_existing,
    )
    result = {"passed": all(item["passed"] for item in checks), "checks": checks}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for item in checks:
            print(f"{'PASS' if item['passed'] else 'FAIL'} {item['name']}: {item['detail']}")
        print("Workflow acceptance passed." if result["passed"] else "Workflow acceptance failed.")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
