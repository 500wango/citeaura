

"""GitHub Pull Request adapter for approved project assets."""

import base64
import re
from pathlib import Path
from urllib.parse import quote

import requests

from api.adapters.engine import geolib
from api.adapters import generated_assets


API_BASE = "https://api.github.com"
_REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_REF_PATTERN = re.compile(r"^[A-Za-z0-9._/-]+$")


def _state_path(project_slug):
    return geolib.project_dir(project_slug) / ".github-prs.json"


def _read_state(project_slug):
    rows = geolib.read_json(_state_path(project_slug), [])
    if not isinstance(rows, list):
        return []
    cleaned = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        number = row.get("number")
        if not isinstance(number, int) or number < 1:
            continue
        cleaned.append({
            key: row[key]
            for key in (
                "number", "url", "status", "title", "branch", "ticket_id",
                "run_id", "updated_at",
            )
            if isinstance(row.get(key), (str, int))
        })
    return cleaned[-100:]


def _repo(config):
    repo = str((config or {}).get("repo") or "").strip()
    if not _REPO_PATTERN.fullmatch(repo):
        raise ValueError("repo must use owner/repo format")
    return repo


def _branch(config):
    branch = str((config or {}).get("branch") or "main").strip()
    if branch.startswith("-") or not _REF_PATTERN.fullmatch(branch) or "//" in branch:
        raise ValueError("invalid GitHub branch")
    return branch


def _directory(config):
    directory = str((config or {}).get("dir") or "").strip().strip("/")
    if not directory:
        return ""
    parts = directory.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("invalid GitHub directory")
    return directory


def _asset_path(project_slug, value):
    project_dir = geolib.project_dir(project_slug).resolve()
    relative = str(value or "").strip()
    if not relative or Path(relative).is_absolute():
        raise ValueError("invalid GitHub asset path")
    target = (project_dir / relative).resolve()
    if project_dir not in target.parents or not target.is_file():
        raise ValueError("GitHub asset must be an existing project file")
    return target.relative_to(project_dir)


def _remote_asset_path(relative):
    """Map a project asset path to the configured repository directory."""
    parts = relative.parts
    if parts and parts[0] == "assets":
        return Path(*parts[1:])
    return relative


def _approved_assets(project_slug, paths):
    """Return deployable project assets that are eligible for a review PR."""
    records = {
        str(item.get("path")): item
        for item in generated_assets.read_project_assets(project_slug).get("tree", [])
        if isinstance(item, dict) and item.get("path")
    }
    assets = []
    for value in paths:
        relative = _asset_path(project_slug, value)
        remote_relative = _remote_asset_path(relative)
        if relative == remote_relative or not remote_relative.parts:
            raise ValueError("GitHub PRs can only include generated assets")
        record = records.get(remote_relative.as_posix())
        if not record or record.get("status") != "deployable":
            raise ValueError("GitHub PR assets must be approved before publishing")
        assets.append(relative)
    return assets


def _session(token):
    if not token:
        raise ValueError("GitHub token is required")
    session = requests.Session()
    session.trust_env = False
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    })
    return session


def _api(session, method, path, *, payload=None):
    url = path if path.startswith("https://") else API_BASE + path
    try:
        response = session.request(method, url, json=payload, timeout=20)
    except requests.RequestException:
        return None, "github_unavailable"
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code >= 400:
        message = data.get("message") if isinstance(data, dict) else None
        return None, str(message or f"github_http_{response.status_code}")
    return data if isinstance(data, dict) else {}, None


def list_prs(project_slug, config, token, *, refresh=False):
    """Return saved PR metadata, optionally refreshing status from GitHub."""
    rows = _read_state(project_slug)
    if not refresh or not token:
        return rows
    repo = _repo(config)
    session = _session(token)
    changed = False
    for row in rows:
        number = row["number"]
        data, error = _api(session, "GET", f"/repos/{repo}/pulls/{number}")
        if error:
            continue
        status = "merged" if data.get("merged_at") else str(data.get("state") or row.get("status") or "open")
        updated_at = data.get("updated_at") or row.get("updated_at")
        if status != row.get("status") or updated_at != row.get("updated_at"):
            row["status"] = status
            row["updated_at"] = updated_at
            changed = True
    if changed:
        with geolib.project_lock(project_slug):
            geolib.write_json(_state_path(project_slug), rows[-100:])
    return rows


def create(
    project_slug, config, token, *, ticket_id, run_id, paths, title="",
    acceptance_criteria=None, evidence_urls=None, sampling_mode=None,
):
    """Upload approved project assets to a new branch and open a review PR."""
    repo = _repo(config)
    base_branch = _branch(config)
    directory = _directory(config)
    ticket = re.sub(r"[^A-Za-z0-9._-]+", "-", str(ticket_id or "").strip()).strip("-.")
    run = re.sub(r"[^A-Za-z0-9._-]+", "-", str(run_id or "").strip()).strip("-.")
    if not ticket or not run:
        raise ValueError("invalid GitHub branch identifier")
    branch = f"citeaura/{ticket}-{run}"[:240]
    assets = _approved_assets(project_slug, paths)
    if len(set(assets)) != len(assets):
        raise ValueError("duplicate GitHub asset path")
    session = _session(token)
    base, error = _api(session, "GET", f"/repos/{repo}/git/ref/heads/{quote(base_branch, safe='')}")
    if error:
        raise RuntimeError(error)
    sha = ((base.get("object") or {}).get("sha"))
    if not isinstance(sha, str) or not sha:
        raise RuntimeError("github_base_branch_invalid")
    _, error = _api(session, "POST", f"/repos/{repo}/git/refs", payload={"ref": f"refs/heads/{branch}", "sha": sha})
    if error:
        raise RuntimeError(error)
    project_dir = geolib.project_dir(project_slug).resolve()
    for relative in assets:
        remote_relative = _remote_asset_path(relative)
        destination = "/".join(part for part in (directory, remote_relative.as_posix()) if part)
        contents = base64.b64encode((project_dir / relative).read_bytes()).decode("ascii")
        payload = {"message": f"CiteAura: {ticket}", "content": contents, "branch": branch}
        _, error = _api(
            session,
            "PUT",
            f"/repos/{repo}/contents/{quote(destination, safe='/')}",
            payload=payload,
        )
        if error and "sha" in error.lower():
            existing, existing_error = _api(
                session, "GET", f"/repos/{repo}/contents/{quote(destination, safe='/')}?ref={quote(branch, safe='')}"
            )
            if existing_error:
                raise RuntimeError(existing_error)
            payload["sha"] = existing.get("sha")
            _, error = _api(session, "PUT", f"/repos/{repo}/contents/{quote(destination, safe='/')}", payload=payload)
        if error:
            raise RuntimeError(error)
    body_parts = []
    if acceptance_criteria:
        body_parts.append("## Acceptance criteria\n" + str(acceptance_criteria))
    if evidence_urls:
        safe_urls = [str(value) for value in evidence_urls if isinstance(value, str) and value.startswith(("https://", "http://"))]
        if safe_urls:
            body_parts.append("## Evidence\n" + "\n".join(f"- {value}" for value in safe_urls))
    if sampling_mode:
        body_parts.append("## Sampling mode\n" + str(sampling_mode))
    pull, error = _api(session, "POST", f"/repos/{repo}/pulls", payload={
        "title": title.strip() or f"CiteAura: {ticket}",
        "head": branch,
        "base": base_branch,
        "body": "\n\n".join(body_parts),
    })
    if error:
        raise RuntimeError(error)
    number = pull.get("number")
    if not isinstance(number, int) or number < 1:
        raise RuntimeError("github_pr_invalid")
    record = {
        "number": number,
        "url": str(pull.get("html_url") or ""),
        "status": str(pull.get("state") or "open"),
        "title": str(pull.get("title") or title or f"CiteAura: {ticket}"),
        "branch": branch,
        "ticket_id": ticket,
        "run_id": run,
        "updated_at": pull.get("updated_at"),
    }
    with geolib.project_lock(project_slug):
        geolib.write_json(_state_path(project_slug), (_read_state(project_slug) + [record])[-100:])
    return record
