"""Run allowlisted pipeline actions with incremental logs for the local UI.

Actions run in subprocesses to isolate HTTP, filesystem, and module-level state.

Each job owns one log file. A cross-process claim allows only one active job per project.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import geolib as G

JOBS_DIR = G.ROOT / ".jobs"
GEO_PY = G.ROOT / "scripts" / "geo.py"

# UI-triggerable actions and their allowlisted arguments.
ACTIONS: dict[str, dict] = {
    "crawl":    {"label": "Crawl site", "args": ["--max-pages"], "desc": "Refresh official-site evidence"},
    "audit":    {"label": "Audit pages", "args": [], "desc": "Evaluate page evidence"},
    "sample":   {"label": "Sample AI answers", "args": ["--limit", "--repeat", "--platforms"],
                 "desc": "Run the question set across configured engines", "slow": True},
    "bootstrap":{"label": "Bootstrap baseline", "args": ["--skip-llm"],
                 "desc": "Extract draft facts, competitors, and questions", "slow": True},
    "deliverables":{"label": "Build deliverables", "args": [], "desc": "Compile diagnostic and execution documents"},
    "plan":     {"label": "Build tasks", "args": [], "desc": "Turn findings into verifiable tasks"},
    "expand":   {"label": "Expand questions", "args": ["--no-llm"],
                 "desc": "Generate reviewable demand-question candidates"},
    "blueprint":{"label": "Build blueprint", "args": [], "desc": "Map channels, content, and coverage"},
    "generate": {"label": "Generate assets", "args": ["--asset", "--draft", "--draft-limit"],
                 "desc": "Generate llms.txt, JSON-LD, snippets, and outlines"},
    "lint":     {"label": "Inspect drafts", "args": [], "desc": "Check generated drafts for unsupported claims"},
    "report":   {"label": "Build report", "args": [], "desc": "Generate Markdown and HTML reports"},
    "verify":   {"label": "Verify tasks", "args": ["--no-recrawl"], "desc": "Refresh evidence and evaluate acceptance checks",
                 "slow": True},
    "deliver":  {"label": "Package delivery", "args": [], "desc": "Build the client delivery package"},
    "sample-sheet": {"label": "Export manual sample sheet", "args": [], "desc": "Prepare non-API sampling"},
    "autopilot":{"label": "Run autopilot", "args": ["--no-sample", "--limit", "--skip-llm"],
                 "desc": "Run baseline, sampling, tasks, assets, and deliverables", "slow": True},
    "serve":    {"label": "Run service cycle", "args": ["--max-pages", "--limit", "--no-sample",
                                                 "--draft", "--draft-limit"],
                 "desc": "Run crawl, audit, sampling, planning, reporting, verification, and delivery", "slow": True},
}

FLAG_ARGS = {"--no-recrawl", "--draft", "--no-sample", "--skip-llm", "--no-llm"}

_lock = threading.Lock()
_running: dict[str, str] = {}   # slug -> job_id
_procs: dict[str, subprocess.Popen] = {}


def _job_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def _log_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.log"


def _claim_path(slug: str) -> Path:
    G.project_dir(slug)
    return JOBS_DIR / "claims" / f"{slug}.json"


def _release_claim(slug: str, job_id: str):
    path = _claim_path(slug)
    try:
        value = json.loads(path.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return
    if value.get("job_id") == job_id:
        path.unlink(missing_ok=True)


def _acquire_claim(slug: str, job_id: str):
    """Use O_EXCL to eliminate cross-thread and cross-process start races."""
    path = _claim_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    for _attempt in range(2):
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            try:
                claim = json.loads(path.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                claim = {}
            current = get(str(claim.get("job_id") or ""))
            young = time.time() - path.stat().st_mtime < 60 if path.exists() else False
            if current and current.get("status") == "running":
                raise RuntimeError("A task is already running for this project. Wait for it to finish or cancel it first.")
            if not current and young:
                raise RuntimeError("A task is already starting for this project. Wait for it to finish or cancel it first.")
            path.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"slug": slug, "job_id": job_id, "claimed_at": G.now_iso()}, handle)
        return
    raise RuntimeError("Could not acquire the project task claim")


def _write(job: dict):
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    G.write_json(_job_path(job["id"]), job)


def get(job_id: str) -> dict | None:
    p = _job_path(job_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:  # noqa: BLE001 - corrupt job metadata must not break polling
        return None


def tail(job_id: str, offset: int = 0) -> tuple[str, int]:
    """Return the log suffix and the next byte offset for incremental polling."""
    p = _log_path(job_id)
    if not p.exists():
        return "", offset
    data = p.read_bytes()
    chunk = data[offset:]
    return chunk.decode("utf-8", "replace"), len(data)


def running_for(slug: str) -> str | None:
    with _lock:
        jid = _running.get(slug)
    if jid:
        j = get(jid)
        if j and j["status"] == "running":
            return jid
    try:
        claim = json.loads(_claim_path(slug).read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    jid = claim.get("job_id")
    j = get(jid) if jid else None
    return jid if j and j.get("status") == "running" else None


def recent(slug: str | None = None, limit: int = 12) -> list[dict]:
    if not JOBS_DIR.exists():
        return []
    out = []
    for f in sorted(JOBS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            j = json.loads(f.read_text("utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if slug and j.get("slug") != slug:
            continue
        j.pop("cmd", None)
        out.append(j)
        if len(out) >= limit:
            break
    return out


def start(slug: str, action: str, params: dict | None = None) -> dict:
    if action not in ACTIONS:
        raise ValueError(f"Unsupported action: {action}")
    spec = ACTIONS[action]
    cmd = [sys.executable, "-u", str(GEO_PY), action, "--slug", slug]
    for k, v in (params or {}).items():
        flag = k if k.startswith("--") else "--" + k
        if flag not in spec["args"]:
            continue
        if flag in FLAG_ARGS:
            if v:
                cmd.append(flag)
        elif v not in (None, "", []):
            cmd += [flag, str(v)]

    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _acquire_claim(slug, job_id)
    job = {
        "id": job_id, "slug": slug, "action": action,
        "label": spec["label"], "status": "running",
        "started_at": G.now_iso(), "finished_at": None, "exit_code": None,
        "cmd": " ".join(cmd[2:]),
    }
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    _write(job)
    logf = _log_path(job["id"]).open("wb")
    logf.write(f"$ geo {' '.join(cmd[3:])}\n".encode())
    logf.flush()

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    try:
        proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT,
                                cwd=str(G.ROOT), env=env, start_new_session=True)
    except Exception as e:  # noqa: BLE001 - spawn failures must transition the job out of running
        logf.close()
        job["status"] = "failed"
        job["error"] = f"{type(e).__name__}: {e}"
        job["finished_at"] = G.now_iso()
        _write(job)
        _release_claim(slug, job["id"])
        raise
    job["pid"] = proc.pid
    _write(job)
    with _lock:
        _running[slug] = job["id"]
        _procs[job["id"]] = proc

    def waiter():
        code = proc.wait()
        logf.close()
        j = get(job["id"]) or job
        j["status"] = "done" if code == 0 else ("stopped" if code < 0 else "failed")
        j["exit_code"] = code
        j["finished_at"] = G.now_iso()
        _write(j)
        with _lock:
            if _running.get(slug) == job["id"]:
                _running.pop(slug, None)
            _procs.pop(job["id"], None)
        _release_claim(slug, job["id"])

    threading.Thread(target=waiter, daemon=True).start()
    return job


def stop(job_id: str) -> bool:
    with _lock:
        proc = _procs.get(job_id)
    if proc:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:  # noqa: BLE001
            proc.terminate()
        return True
    # After a service restart, fall back to the persisted process group ID.
    job = get(job_id)
    pid = (job or {}).get("pid")
    if not pid or job.get("status") != "running":
        return False
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except Exception:  # noqa: BLE001
        return False
    job["status"] = "stopped"
    job["finished_at"] = G.now_iso()
    _write(job)
    _release_claim(job.get("slug", ""), job_id)
    return True


def reap_orphans() -> int:
    """Mark stale running records as interrupted when their process has exited."""
    if not JOBS_DIR.exists():
        return 0
    reaped = 0
    for f in JOBS_DIR.glob("*.json"):
        try:
            job = json.loads(f.read_text("utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if job.get("status") != "running":
            continue
        pid = job.get("pid")
        if not pid and time.time() - f.stat().st_mtime < 60:
            continue  # start() persists running before adding the PID; preserve the short handoff window.
        alive = False
        if pid:
            try:
                os.kill(pid, 0)
                alive = True
            except ProcessLookupError:
                alive = False
            except PermissionError:
                alive = True
        if alive:
            continue
        job["status"] = "interrupted"
        job["finished_at"] = G.now_iso()
        _write(job)
        _release_claim(job.get("slug", ""), job.get("id", ""))
        reaped += 1
    if reaped:
        G.info(f"Reclaimed {reaped} interrupted task records")
    return reaped
