"""Run allowlisted pipeline actions with incremental logs for the local UI.

Actions run in subprocesses to isolate HTTP, filesystem, and module-level state.

Each job owns one log file. A cross-process claim allows only one active job per project.
"""

from __future__ import annotations

import codecs
import json
import os
import re
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
INT_ARG_LIMITS = {
    "--max-pages": (1, 1000),
    "--limit": (1, 1000),
    "--repeat": (1, 20),
    "--draft-limit": (1, 50),
}
LIST_ARG_VALUES = {
    "--asset": {"llms", "jsonld", "snippets", "outlines"},
}
ARG_TOKEN_OK = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_lock = threading.Lock()
_running: dict[str, str] = {}   # slug -> job_id
_procs: dict[str, subprocess.Popen] = {}
STOP_GRACE_SECONDS = 5.0
STOP_KILL_SECONDS = 2.0
MAX_TAIL_BYTES = 256 * 1024
JOB_RETENTION_DAYS = 30
MAX_JOB_RECORDS = 200
STALE_TEMP_SECONDS = 24 * 60 * 60
JOB_ID_OK = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
TERMINAL_STATUSES = {"done", "failed", "stopped", "interrupted"}


def _job_path(job_id: str) -> Path:
    if not JOB_ID_OK.fullmatch(str(job_id or "")):
        raise ValueError("Invalid job id")
    return JOBS_DIR / f"{job_id}.json"


def _log_path(job_id: str) -> Path:
    if not JOB_ID_OK.fullmatch(str(job_id or "")):
        raise ValueError("Invalid job id")
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


def _validate_arg(flag: str, value):
    """Validate an allowlisted CLI value before it reaches a subprocess."""
    if flag in FLAG_ARGS:
        if not isinstance(value, bool):
            raise ValueError(f"{flag} must be a boolean")
        return value
    if flag in INT_ARG_LIMITS:
        if isinstance(value, bool):
            raise ValueError(f"{flag} must be an integer")
        try:
            parsed = int(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{flag} must be an integer") from exc
        if str(value).strip() != str(parsed):
            raise ValueError(f"{flag} must be an integer")
        low, high = INT_ARG_LIMITS[flag]
        if not low <= parsed <= high:
            raise ValueError(f"{flag} must be between {low} and {high}")
        return parsed
    if flag in ("--platforms", "--asset"):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{flag} must be a comma-separated list")
        values = [item.strip() for item in value.split(",")]
        if any(not ARG_TOKEN_OK.fullmatch(item) for item in values):
            raise ValueError(f"{flag} contains an invalid token")
        if flag == "--asset" and any(item not in LIST_ARG_VALUES[flag] for item in values):
            raise ValueError(f"{flag} contains an unsupported asset")
        if len(set(values)) != len(values):
            raise ValueError(f"{flag} contains duplicate values")
        return ",".join(values)
    return value


def get(job_id: str) -> dict | None:
    try:
        p = _job_path(job_id)
    except ValueError:
        return None
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:  # noqa: BLE001 - corrupt job metadata must not break polling
        return None


def tail(job_id: str, offset: int = 0) -> tuple[str, int]:
    """Return the log suffix and the next byte offset for incremental polling."""
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    p = _log_path(job_id)
    if not p.exists():
        return "", offset
    size = p.stat().st_size
    if offset >= size:
        return "", size
    with p.open("rb") as handle:
        handle.seek(offset)
        chunk = handle.read(MAX_TAIL_BYTES)
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    text = decoder.decode(chunk, final=False)
    pending, _ = decoder.getstate()
    consumed = len(chunk) - len(pending)
    return text, offset + consumed


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
    entries = []
    for f in JOBS_DIR.glob("*.json"):
        try:
            entries.append((f.stat().st_mtime, f))
        except OSError:
            continue
    out = []
    for _, f in sorted(entries, key=lambda item: item[0], reverse=True):
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


def _env_positive_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def prune_history(retention_days: int | None = None, keep: int | None = None,
                  now: float | None = None) -> int:
    """Remove old terminal job records, paired logs, and stale temporary files."""
    if not JOBS_DIR.exists():
        return 0
    if retention_days is None:
        retention_days = _env_positive_int("GEO_JOB_RETENTION_DAYS", JOB_RETENTION_DAYS)
    if keep is None:
        keep = _env_positive_int("GEO_MAX_JOB_RECORDS", MAX_JOB_RECORDS)
    if retention_days < 1 or keep < 1:
        raise ValueError("retention_days and keep must be positive integers")
    now = time.time() if now is None else now
    cutoff = now - retention_days * 24 * 60 * 60
    terminal = []
    for path in JOBS_DIR.glob("*.json"):
        try:
            job = json.loads(path.read_text("utf-8"))
            mtime = path.stat().st_mtime
        except (OSError, json.JSONDecodeError):
            continue
        if job.get("status") in TERMINAL_STATUSES:
            terminal.append((mtime, path))

    terminal.sort(key=lambda item: item[0], reverse=True)
    remove = {path for index, (mtime, path) in enumerate(terminal)
              if mtime < cutoff or index >= keep}
    removed = 0
    for path in remove:
        try:
            path.unlink(missing_ok=True)
            path.with_suffix(".log").unlink(missing_ok=True)
            removed += 1
        except OSError:
            continue

    for path in JOBS_DIR.glob("*.tmp"):
        try:
            if now - path.stat().st_mtime >= STALE_TEMP_SECONDS:
                path.unlink()
                removed += 1
        except OSError:
            continue
    if removed:
        G.info(f"Pruned {removed} expired task artifacts")
    return removed


def start(slug: str, action: str, params: dict | None = None) -> dict:
    if action not in ACTIONS:
        raise ValueError(f"Unsupported action: {action}")
    spec = ACTIONS[action]
    if params is not None and not isinstance(params, dict):
        raise ValueError("Job parameters must be an object")
    cmd = [sys.executable, "-u", str(GEO_PY), action, "--slug", slug]
    for k, v in (params or {}).items():
        flag = k if k.startswith("--") else "--" + k
        if flag not in spec["args"]:
            continue
        if v is None:
            continue
        v = _validate_arg(flag, v)
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
    logf = None
    proc = None
    try:
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        _write(job)
        logf = _log_path(job["id"]).open("wb")
        logf.write(f"$ geo {' '.join(cmd[3:])}\n".encode())
        logf.flush()
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT,
                                cwd=str(G.ROOT), env=env, start_new_session=True)
        job["pid"] = proc.pid
        _write(job)
        with _lock:
            _running[slug] = job["id"]
            _procs[job["id"]] = proc
    except BaseException as e:
        if proc is not None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:  # noqa: BLE001 - cleanup must preserve the original startup error
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            try:
                proc.wait(timeout=STOP_KILL_SECONDS)
            except Exception:  # noqa: BLE001 - cleanup must preserve the original startup error
                pass
        if logf is not None:
            logf.close()
        job["status"] = "failed"
        job["error"] = f"{type(e).__name__}: {e}"
        job["finished_at"] = G.now_iso()
        try:
            _write(job)
        except OSError:
            pass
        _release_claim(slug, job["id"])
        raise

    def waiter():
        code = proc.wait()
        try:
            j = get(job["id"]) or job
            j["status"] = ("stopped" if j.get("stop_requested_at") else
                           ("done" if code == 0 else ("stopped" if code < 0 else "failed")))
            j["exit_code"] = code
            j["finished_at"] = G.now_iso()
            _write(j)
        finally:
            logf.close()
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
        job = get(job_id)
        if job and job.get("status") == "running":
            job["stop_requested_at"] = G.now_iso()
            _write(job)
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception:  # noqa: BLE001
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
        try:
            code = proc.wait(timeout=STOP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception:  # noqa: BLE001
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            try:
                code = proc.wait(timeout=STOP_KILL_SECONDS)
            except subprocess.TimeoutExpired:
                return False
        job = get(job_id)
        if job and job.get("status") == "running":
            job["status"] = "stopped"
            job["exit_code"] = code
            job["finished_at"] = G.now_iso()
            _write(job)
            _release_claim(job.get("slug", ""), job_id)
        return True
    # After a service restart, fall back to the persisted process group ID.
    job = get(job_id)
    pid = (job or {}).get("pid")
    if not pid or job.get("status") != "running":
        return False
    try:
        pgid = os.getpgid(pid)
        if pgid != pid:
            return False
        os.killpg(pgid, signal.SIGTERM)
    except Exception:  # noqa: BLE001
        return False
    final_signal = signal.SIGTERM
    deadline = time.monotonic() + STOP_GRACE_SECONDS
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        except PermissionError:
            pass
        time.sleep(0.05)
    else:
        final_signal = signal.SIGKILL
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except Exception:  # noqa: BLE001
            return False
        deadline = time.monotonic() + STOP_KILL_SECONDS
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            except PermissionError:
                pass
            time.sleep(0.05)
        else:
            return False
    job["status"] = "stopped"
    job["exit_code"] = -final_signal
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
