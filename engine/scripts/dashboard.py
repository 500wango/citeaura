"""Serve the standalone GEO monitoring dashboard and its local JSON API.

Run with ``python3 scripts/geo.py ui``. The frontend is ``scripts/ui.html``;
ticket status changes are persisted to tasks.json.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import threading
import time
import webbrowser
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

try:
    import geolib as G
except ModuleNotFoundError as e:
    raise SystemExit(f"Missing dependency: {e.name}. Please run: pip3 install requests beautifulsoup4 lxml") from e
import jobs as J
import tasks as T

UI = Path(__file__).resolve().parent / "ui.html"
MAX_BODY_BYTES = 1_000_000
IMPORT_FILE_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,126}\.md$", re.I)
_env_lock = threading.Lock()


# ---------------------------------------------------------------- Data aggregation

def list_projects() -> list[dict]:
    out = []
    if not G.WORK.exists():
        return out
    for d in sorted(G.WORK.iterdir()):
        cfg_path = d / "geo.json"
        if not cfg_path.exists():
            continue
        cfg = G.read_json(cfg_path, {})
        audit = G.read_json(d / "audit.json", {})
        td = G.read_json(d / "tasks.json", {})
        s = td.get("summary", {})
        out.append({
            "slug": d.name,
            "name": cfg.get("brand", {}).get("name", d.name),
            "site": cfg.get("brand", {}).get("site", ""),
            "market": cfg.get("market", "cn"),
            "avg_score": audit.get("avg_score"),
            "pages": audit.get("page_count"),
            "tasks_total": s.get("total", 0),
            "tasks_done": s.get("by_status", {}).get("done", 0),
            "p0_open": sum(1 for t in td.get("tasks", []) if isinstance(t, dict)
                           and t.get("priority") == "P0" and t.get("status") != "done"),
        })
    return out


def project(slug: str) -> dict:
    pdir = G.project_dir(slug)
    cfg = G.load_config(slug)
    audit = G.read_json(pdir / "audit.json", {})
    td = G.read_json(pdir / "tasks.json", {"tasks": [], "summary": {}})

    verify_hist = []
    vdir = pdir / "verify"
    import verify as V
    for f in sorted(vdir.glob("*.json"), key=V.report_key) if vdir.exists() else []:
        v = G.read_json(f, {})
        rs = v.get("results", [])
        verify_hist.append({
            "date": (v.get("verified_at") or f.stem)[:10],
            "pass": sum(1 for r in rs if isinstance(r, dict) and r.get("verdict") == "pass"),
            "fail": sum(1 for r in rs if isinstance(r, dict) and r.get("verdict") == "fail"),
            "manual": sum(1 for r in rs if isinstance(r, dict) and r.get("verdict") == "manual"),
            "avg_score": v.get("audit_avg_score"),
        })

    deliveries = sorted((d.name for d in (pdir / "delivery").iterdir() if d.is_dir()),
                        reverse=True) if (pdir / "delivery").exists() else []

    lint = G.read_json(pdir / "assets" / "drafts" / "_lint.json", None)

    return {
        "slug": slug,
        "brand": cfg.get("brand", {}),
        "market": cfg.get("market", "cn"),
        "audit": {"avg_score": audit.get("avg_score"), "page_count": audit.get("page_count"),
                  "grade_distribution": audit.get("grade_distribution", {}),
                  "language_coverage": audit.get("language_coverage", {}),
                  "site": audit.get("site", {}), "site_issues": audit.get("site_issues", []),
                  "block_gap": audit.get("block_gap", []),
                  "pages": sorted(audit.get("pages", []),
                                  key=lambda p: (p.get("score") is None, p.get("score") or 0))[:40]},
        "tasks": td.get("tasks", []),
        "verify_history": verify_hist,
        "deliveries": deliveries,
        "lint": {"total": (lint or {}).get("total_issues", 0), "high": (lint or {}).get("high", 0)},
        "blueprint": G.read_json(pdir / "blueprint.json", None),
        "distribution": G.read_json(pdir / "distribution.json", {}),
        "question_count": len(cfg.get("questions", [])),
        "deliverables_files": sorted(f.name for f in (pdir / "deliverables").glob("*.html"))
                              if (pdir / "deliverables").exists() else [],
        "analytics": _analytics(slug),
        "facts_struct": _facts_struct(slug),
    }


def _facts_struct(slug: str):
    try:
        import generate
        f = generate.parse_facts(slug)
        f.pop("raw", None)
        return f
    except Exception:  # noqa: BLE001
        return {}


def workbench(slug: str, qid: str) -> dict:
    """Locate content, draft, and outline files for a question."""
    pdir = G.project_dir(slug)
    cfg = G.load_config(slug)
    q = next((x for x in cfg.get("questions", []) if x.get("id") == qid), None)
    sources = []
    cdir = pdir / "content"
    if cdir.exists():
        for f in sorted(cdir.glob("*.md")):
            if qid and qid in f.read_text("utf-8", "replace")[:800]:
                sources.append({"kind": "content", "path": f.name})
    for kind, sub in (("draft", "drafts"), ("outline", "outlines")):
        f = pdir / "assets" / sub / f"{qid}.md"
        if f.exists():
            sources.append({"kind": kind, "path": f"{sub}/{qid}.md"})
    return {"question": q, "sources": sources}


def _analytics(slug: str):
    try:
        import analytics
        return analytics.build(slug)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------- HTTP

def asset_tree(slug: str) -> list[dict]:
    """List text assets available for dashboard preview."""
    adir = G.project_dir(slug) / "assets"
    out = []
    if not adir.exists():
        return out
    for f in sorted(adir.rglob("*")):
        if not f.is_symlink() and f.is_file() and f.suffix in (".txt", ".json", ".html", ".md"):
            rel = f.relative_to(adir).as_posix()
            out.append({"path": rel, "size": f.stat().st_size,
                        "group": rel.split("/")[0] if "/" in rel else "root"})
    return out


def read_asset(slug: str, rel: str) -> dict:
    base = (G.project_dir(slug) / "assets").resolve()
    target = (base / rel).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise PermissionError(rel) from None
    if not target.is_file():
        raise FileNotFoundError(rel)
    return {"path": rel, "text": target.read_text("utf-8", "replace")}


def write_env(updates: dict[str, str]):
    """Update the project .env file and synchronize the current process."""
    path = G.ROOT / ".env"
    with _env_lock:
        lines = path.read_text("utf-8").splitlines() if path.exists() else []
        for k, v in updates.items():
            pat = re.compile(rf"\s*(export\s+)?{re.escape(k)}\s*=")
            lines = [ln for ln in lines if not pat.match(ln)]
            if v:
                lines.append(f"{k}={v}")
        text = "\n".join(lines) + ("\n" if lines else "")
        tmp = path.with_name(f".env.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            tmp.write_text(text, "utf-8")
            tmp.chmod(0o600)
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
        for k, v in updates.items():
            if v:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)


def trusted_request(host: str, origin: str = "", fetch_site: str = "") -> bool:
    """Accept only loopback hosts and reject browser cross-site mutations."""
    try:
        parsed_host = urlparse("//" + str(host or ""))
        hostname = (parsed_host.hostname or "").lower()
    except ValueError:
        return False
    if hostname not in ("127.0.0.1", "localhost", "::1"):
        return False
    if origin:
        try:
            parsed_origin = urlparse(origin)
        except ValueError:
            return False
        if parsed_origin.scheme != "http" or parsed_origin.netloc.lower() != str(host).lower():
            return False
    return fetch_site.lower() not in ("cross-site", "same-site")


def sample_import_path(slug: str, filename: str) -> Path:
    """Return a project-local Markdown sheet path."""
    name = str(filename or "").strip()
    if not IMPORT_FILE_OK.fullmatch(name) or Path(name).name != name:
        raise ValueError("invalid_sample_sheet_filename")
    return G.project_dir(slug) / "samples" / name


def create_project(url: str, name: str, slug: str, market: str, max_pages: int) -> dict:
    import geo as CLI

    class A:
        pass
    a = A()
    a.url, a.name, a.slug, a.market, a.max_pages = url, name or None, slug or None, market, max_pages
    a.force = False
    return CLI.cmd_init(a)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            raise ValueError("content_length_must_be_integer") from None
        if n < 0 or n > MAX_BODY_BYTES:
            raise ValueError(f"request_body_must_not_exceed_{MAX_BODY_BYTES}_bytes")
        body = json.loads(self.rfile.read(n) or b"{}")
        if not isinstance(body, dict):
            raise ValueError("request_body_must_be_object")
        return body

    def _trusted(self, write: bool = False) -> bool:
        return trusted_request(
            self.headers.get("Host", ""),
            self.headers.get("Origin", "") if write else "",
            self.headers.get("Sec-Fetch-Site", "") if write else "",
        )

    # ------------------------------------------------------------ GET
    def do_GET(self):
        if not self._trusted():
            return self._json({"error": "untrusted_request_host"}, 403)
        u = urlparse(self.path)
        p, q = unquote(u.path), parse_qs(u.query)
        try:
            if p in ("/", "/index.html"):
                return self._send(200, UI.read_bytes(), "text/html; charset=utf-8")
            if p == "/api/projects":
                return self._json(list_projects())
            if p == "/api/actions":
                return self._json(J.ACTIONS)
            if p.startswith("/api/p/"):
                return self._json(project(p[len("/api/p/"):]))
            if p.startswith("/api/config/"):
                slug = p[len("/api/config/"):]
                return self._json(G.read_json(G.project_dir(slug) / "geo.json", {}))
            if p.startswith("/api/facts/"):
                slug = p[len("/api/facts/"):]
                f = G.project_dir(slug) / "content" / "facts.md"
                return self._json({"exists": f.exists(),
                                   "text": f.read_text("utf-8") if f.exists() else ""})
            if p.startswith("/api/assets/"):
                return self._json(asset_tree(p[len("/api/assets/"):]))
            if p.startswith("/api/asset/"):
                slug = p[len("/api/asset/"):]
                return self._json(read_asset(slug, q.get("path", [""])[0]))
            if p.startswith("/api/workbench/"):
                slug = p[len("/api/workbench/"):]
                return self._json(workbench(slug, q.get("qid", [""])[0]))
            if p == "/api/keys":
                import sample as S
                rows = []
                for code, spec in S.PROVIDERS.items():
                    key = os.environ.get(spec["key_env"], "")
                    menv = spec.get("model_env")
                    rows.append({"code": code, "label": spec["name"], "market": spec["market"],
                                 "search": spec.get("search", False), "env": spec["key_env"],
                                 "ok": S.available(code),
                                 "key_tail": key[-4:] if len(key) >= 8 else "",
                                 "model": os.environ.get(menv) or spec.get("model", "") if menv else spec.get("model", ""),
                                 "model_env": menv,
                                 "model_set": bool(menv and os.environ.get(menv)),
                                 "note": spec.get("note", "")})
                for code, (label, mk) in S.MANUAL_ONLY.items():
                    rows.append({"code": code, "label": label, "market": mk,
                                 "search": True, "env": None, "ok": None})
                return self._json(rows)
            if p.startswith("/api/factcheck/"):
                slug = p[len("/api/factcheck/"):]
                return self._json(G.read_json(G.project_dir(slug) / "factcheck.json", []) or [])
            if p.startswith("/api/expand/"):
                slug = p[len("/api/expand/"):]
                return self._json(G.read_json(G.project_dir(slug) / "expand.json", {}) or {})
            if p.startswith("/api/publish/"):
                import publish as P
                slug = p[len("/api/publish/"):]
                pubs = []
                for code, spec in P.PUBLISHERS.items():
                    cfg = P._cfg(slug, code)
                    pubs.append({"code": code, "name": spec["name"], "note": spec["note"],
                                 "env": spec["env"], "missing": P.missing_env(code),
                                 "cfg": [{"key": k, "hint": h, "value": cfg.get(k, "")}
                                         for k, h in spec["cfg"]]})
                return self._json({"publishers": pubs, "records": P.records(slug)})
            if p.startswith("/api/content/"):
                slug = p[len("/api/content/"):]
                base = (G.project_dir(slug) / "content").resolve()
                rel = q.get("path", [""])[0]
                if rel:
                    target = (base / rel).resolve()
                    try:
                        target.relative_to(base)
                    except ValueError:
                        return self._json({"error": "invalid_path"}, 403)
                    if not target.is_file():
                        return self._json({"error": "file_not_found"}, 404)
                    return self._json({"path": rel, "text": target.read_text("utf-8", "replace")})
                files = sorted(f.name for f in base.glob("*.md")) if base.exists() else []
                return self._json({"files": files})
            if p == "/api/jobs":
                slug = q.get("slug", [None])[0]
                return self._json({"jobs": J.recent(slug),
                                   "running": J.running_for(slug) if slug else None})
            if p.startswith("/api/job/"):
                jid = p[len("/api/job/"):]
                job = J.get(jid)
                if not job:
                    return self._json({"error": "job not found"}, 404)
                try:
                    off = int(q.get("offset", ["0"])[0])
                except ValueError:
                    return self._json({"error": "offset_must_be_integer"}, 400)
                if off < 0:
                    return self._json({"error": "offset_must_be_non_negative"}, 400)
                text, new_off = J.tail(jid, off)
                return self._json({"job": job, "log": text, "offset": new_off})
            if p.startswith("/api/files/"):
                slug = p[len("/api/files/"):]
                pdir = G.project_dir(slug)
                def ls(sub, pat="*"):
                    d = pdir / sub
                    return sorted((x.name for x in d.glob(pat)), reverse=True) if d.exists() else []
                dv = pdir / "deliverables"
                return self._json({
                    "reports": [d for d in ls("reports") if d.startswith("2")],
                    "deliveries": [d for d in ls("delivery") if d.startswith("2")],
                    "samples": ls("samples", "*.md"),
                    "deliverables": sorted(f.name for f in dv.glob("*.html")) if dv.exists() else [],
                    "content": sorted(f.name for f in (pdir / "content").glob("*.md"))
                               if (pdir / "content").exists() else [],
                })
            if p.startswith("/files/"):
                rel = p[len("/files/"):]
                target = (G.WORK / rel).resolve()
                try:
                    target.relative_to(G.WORK.resolve())
                except ValueError:
                    return self._send(403, b"forbidden", "text/plain")
                if not target.is_file():
                    return self._send(404, b"not found", "text/plain")
                ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype in ("application/json",):
                    ctype += "; charset=utf-8"
                return self._send(200, target.read_bytes(), ctype)
            return self._send(404, b"not found", "text/plain")
        except FileNotFoundError:
            return self._json({"error": "file_not_found"}, 404)
        except PermissionError:
            return self._json({"error": "invalid_path"}, 403)
        except SystemExit:
            return self._json({"error": "project_not_found"}, 404)
        except Exception as e:  # noqa: BLE001
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    # ------------------------------------------------------------ POST
    def do_POST(self):
        if not self._trusted(write=True):
            return self._json({"ok": False, "error": "untrusted_request_origin"}, 403)
        p = unquote(urlparse(self.path).path)
        try:
            body = self._body()

            if p == "/api/task":
                missing = [k for k in ("slug", "id", "status") if k not in body]
                if missing:
                    return self._json({"error": f"missing_parameters: {', '.join(missing)}"}, 400)
                valid = ("todo", "doing", "done", "blocked", "wontfix")
                if body["status"] not in valid:
                    return self._json({"ok": False, "error": f"invalid_status: {body['status']}",
                                       "valid": list(valid)}, 400)
                try:
                    t = T.set_status(body["slug"], body["id"], body["status"], body.get("note", ""))
                except KeyError as e:
                    return self._json({"error": e.args[0] if e.args else str(e)}, 404)
                return self._json({"ok": True, "task": t})

            if p == "/api/init":
                url = (body.get("url") or "").strip()
                if not url:
                    return self._json({"ok": False, "error": "site_url_required"}, 400)
                cfg = create_project(url, body.get("name", ""), body.get("slug", ""),
                                     body.get("market", "cn"), int(body.get("max_pages", 25)))
                return self._json({"ok": True, "slug": cfg["slug"]})

            if p == "/api/run":
                job = J.start(body["slug"], body["action"], body.get("params") or {})
                return self._json({"ok": True, "job": job})

            if p.startswith("/api/job/") and p.endswith("/stop"):
                jid = p[len("/api/job/"):-len("/stop")]
                return self._json({"ok": J.stop(jid)})

            if p.startswith("/api/config/"):
                slug = p[len("/api/config/"):]
                with G.project_lock(slug):
                    cur = G.read_json(G.project_dir(slug) / "geo.json", {})
                    cur.update(body)
                    G.save_config(slug, cur)
                return self._json({"ok": True})

            if p.startswith("/api/facts/"):
                slug = p[len("/api/facts/"):]
                f = G.project_dir(slug) / "content" / "facts.md"
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(body.get("text", ""), "utf-8")
                return self._json({"ok": True})

            if p.startswith("/api/asset/"):
                slug = p[len("/api/asset/"):]
                base = (G.project_dir(slug) / "assets").resolve()
                target = (base / body["path"]).resolve()
                try:
                    target.relative_to(base)
                except ValueError:
                    return self._json({"ok": False, "error": "invalid_path"}, 403)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(body.get("text", ""), "utf-8")
                return self._json({"ok": True})

            if p == "/api/precheck":
                import analytics
                return self._json(analytics.precheck(body.get("text", "")))

            if p.startswith("/api/factcheck/"):
                slug = p[len("/api/factcheck/"):]
                items = body.get("items")
                if not isinstance(items, list):
                    return self._json({"ok": False, "error": "items_must_be_array"}, 400)
                G.write_json(G.project_dir(slug) / "factcheck.json", items)
                return self._json({"ok": True, "count": len(items)})

            if p.startswith("/api/content/"):
                slug = p[len("/api/content/"):]
                base = (G.project_dir(slug) / "content").resolve()
                rel = (body.get("path") or "").strip()
                # Accept plain Markdown filenames while blocking traversal and hidden files.
                if ("/" in rel or "\\" in rel or ".." in rel or rel.startswith(".")
                        or not rel.endswith(".md") or len(rel) <= 3):
                    return self._json({"ok": False, "error": "invalid_markdown_filename"}, 400)
                base.mkdir(parents=True, exist_ok=True)
                (base / rel).write_text(body.get("text", ""), "utf-8")
                return self._json({"ok": True})

            if p == "/api/keys":
                import publish as P
                import sample as S
                allowed = set()
                for spec in S.PROVIDERS.values():
                    allowed.add(spec["key_env"])
                    if spec.get("model_env"):
                        allowed.add(spec["model_env"])
                for spec in P.PUBLISHERS.values():
                    allowed.update(spec["env"])
                updates = body.get("updates")
                if not isinstance(updates, dict) or not updates:
                    return self._json({"ok": False, "error": "updates_must_be_nonempty_object"}, 400)
                bad = [k for k in updates if k not in allowed]
                if bad:
                    return self._json({"ok": False,
                                       "error": f"environment_variables_not_allowed: {', '.join(bad)}"}, 400)
                clean = {k: str(v or "").strip() for k, v in updates.items()}
                if any("\n" in v or "\r" in v for v in clean.values()):
                    return self._json({"ok": False, "error": "environment_value_cannot_contain_newline"}, 400)
                write_env(clean)
                return self._json({"ok": True})

            if p.startswith("/api/publishcfg/"):
                import publish as P
                slug = p[len("/api/publishcfg/"):]
                code = body.get("platform")
                if code not in P.PUBLISHERS:
                    return self._json({"ok": False, "error": f"unknown_channel: {code}"}, 400)
                if not isinstance(body.get("cfg") or {}, dict):
                    return self._json({"ok": False, "error": "cfg_must_be_object"}, 400)
                keys = {k for k, _ in P.PUBLISHERS[code]["cfg"]}
                with G.project_lock(slug):
                    cfg = G.read_json(G.project_dir(slug) / "geo.json", {})
                    pub = cfg.setdefault("publishing", {})
                    pub[code] = {k: str(v or "").strip() for k, v in (body.get("cfg") or {}).items()
                                 if k in keys}
                    G.save_config(slug, cfg)
                return self._json({"ok": True})

            if p.startswith("/api/publish/"):
                # Publishing runs only after an explicit user request.
                import publish as P
                slug = p[len("/api/publish/"):]
                r = P.publish(slug, body.get("platform", ""), body.get("path", ""),
                              body.get("title", ""))
                return self._json(r, 200 if r.get("ok") else 400)

            if p.startswith("/api/distribution/"):
                # Distribution records are explicit human confirmations.
                slug = p[len("/api/distribution/"):]
                qid, ch = (body.get("qid") or "").strip(), (body.get("channel") or "").strip()
                if not qid or not ch:
                    return self._json({"ok": False, "error": "qid_and_channel_required"}, 400)
                path = G.project_dir(slug) / "distribution.json"
                with G.project_lock(slug):
                    dist = G.read_json(path, {})
                    if body.get("on"):
                        dist.setdefault(qid, {})[ch] = G.now_iso()
                    else:
                        dist.get(qid, {}).pop(ch, None)
                        if not dist.get(qid):
                            dist.pop(qid, None)
                    G.write_json(path, dist)
                return self._json({"ok": True, "distribution": dist})

            if p == "/api/questions-add":
                slug = body.get("slug") or ""
                items = body.get("items")
                if (not slug or not isinstance(items, list) or not items
                        or any(not isinstance(item, dict) for item in items)):
                    return self._json({"ok": False, "error": "slug_and_items_required"}, 400)
                with G.project_lock(slug):
                    cfg = G.read_json(G.project_dir(slug) / "geo.json", {})
                    qs = cfg.setdefault("questions", [])
                    existing = {q.get("text", "").strip() for q in qs}
                    series = {"cn": 1, "global": 101, "both": 901}
                    used = {int(m.group(1)) for q in qs
                            if (m := re.match(r"q(\d+)$", str(q.get("id", ""))))}
                    added = []
                    for it in items:
                        text = str(it.get("text") or "").strip()
                        mk = it.get("market") if it.get("market") in series else "cn"
                        grp = str(it.get("group") or "scenario").strip() or "scenario"
                        if not text or text in existing:
                            continue
                        n = series[mk]
                        while n in used:
                            n += 1
                        used.add(n)
                        q = {"id": f"q{n:03d}", "group": grp, "market": mk, "text": text,
                             "source": "expand"}
                        qs.append(q)
                        existing.add(text)
                        added.append(q)
                    if added:
                        G.save_config(slug, cfg)
                return self._json({"ok": True, "added": len(added),
                                   "ids": [q["id"] for q in added]})

            if p == "/api/sample-import":
                import sample as S
                if not body.get("slug") or not body.get("file"):
                    return self._json({"ok": False, "error": "slug_and_file_required"}, 400)
                if body.get("text") is not None and not isinstance(body["text"], str):
                    return self._json({"ok": False, "error": "text_must_be_string"}, 400)
                path = sample_import_path(body["slug"], body["file"])
                if body.get("text") is not None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(body["text"], "utf-8")
                S.sample_import(body["slug"], str(path))
                return self._json({"ok": True})

            return self._send(404, b"not found", "text/plain")
        except SystemExit:  # G.die triggers sys.exit
            return self._json({"ok": False, "error": "operation_failed_or_slug_conflict"}, 400)
        except (ValueError, RuntimeError) as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)


def _monitor_tick():
    """Trigger a scheduled cycle when monitor.next_run is due."""
    for d in (G.WORK.iterdir() if G.WORK.exists() else []):
        cfg_path = d / "geo.json"
        if not cfg_path.exists():
            continue
        cfg = G.read_json(cfg_path, {})
        mon = cfg.get("monitor") or {}
        every = mon.get("every_days")
        if not every or (mon.get("next_run") or "") > G.today():
            continue
        try:
            days = int(every)
            if days < 1:
                raise ValueError
        except (TypeError, ValueError):
            G.info(f"Scheduled run skipped for {d.name}: every_days must be a positive integer")
            continue
        if J.running_for(d.name):
            continue
        try:
            J.start(d.name, "serve", {})
            next_run = (date.today() + timedelta(days=days)).isoformat()
            with G.project_lock(d.name):
                latest = G.read_json(cfg_path, {})
                latest_mon = latest.get("monitor") or {}
                latest_mon["next_run"] = next_run
                latest["monitor"] = latest_mon
                G.save_config(d.name, latest)
            G.info(f"Scheduled run triggered: {d.name}, next run at {next_run}")
        except (ValueError, RuntimeError) as e:
            G.info(f"Scheduled run skipped for {d.name}: {e}")


MONITOR_INTERVAL_SECONDS = 1800


def _monitor_loop(stop_event=None, interval: float = MONITOR_INTERVAL_SECONDS):
    stop_event = stop_event or threading.Event()
    while not stop_event.is_set():
        try:
            J.reap_orphans()
            J.prune_history()
            _monitor_tick()
        except Exception as e:  # noqa: BLE001 - scheduler loop must stay alive
            G.info(f"Scheduled run error: {type(e).__name__}: {e}")
        stop_event.wait(interval)


def run(port: int = 8765, open_browser: bool = True):
    J.reap_orphans()
    J.prune_history()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    monitor_stop = threading.Event()
    monitor = threading.Thread(target=_monitor_loop, args=(monitor_stop,), daemon=True)
    monitor.start()
    url = f"http://127.0.0.1:{port}/"
    G.info(f"Dashboard started: {url} (Ctrl+C to quit)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        G.info("Dashboard stopped")
    finally:
        monitor_stop.set()
        monitor.join(timeout=2)
        srv.server_close()
