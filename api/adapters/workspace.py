"""引擎工作台文件接口的租户内适配。"""

import os
import re
from pathlib import Path

from api.adapters.engine import geolib


QUESTION_MARKETS = {"cn", "global", "both"}
TEXT_SUFFIXES = {".txt", ".json", ".html", ".md"}


def _safe_target(base: Path, relative: str, suffixes=None) -> Path:
    relative = str(relative or "").strip()
    if not relative:
        raise ValueError("file path is required")
    base = base.resolve()
    target = (base / relative).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise ValueError("invalid file path") from None
    if suffixes is not None and target.suffix not in suffixes:
        raise ValueError("unsupported file type")
    return target


def _write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(text, "utf-8")
    os.replace(temporary, path)


def _validated_questions(questions):
    if not isinstance(questions, list) or len(questions) > 1000:
        raise ValueError("questions must be an array with at most 1000 items")
    validated = []
    used_ids = set()
    for item in questions:
        if not isinstance(item, dict):
            raise ValueError("each question must be an object")
        qid = str(item.get("id") or "").strip()
        text = str(item.get("text") or "").strip()
        market = item.get("market")
        group = str(item.get("group") or "推荐").strip() or "推荐"
        if not re.fullmatch(r"q\d{3,6}", qid) or qid in used_ids:
            raise ValueError("question ids must be unique qNNN values")
        if not text or len(text) > 1000:
            raise ValueError("question text is required and must not exceed 1000 characters")
        if market not in QUESTION_MARKETS:
            raise ValueError("question market must be cn, global, or both")
        validated.append({**item, "id": qid, "text": text, "market": market, "group": group})
        used_ids.add(qid)
    return validated


def read_config(project_slug: str) -> dict:
    return geolib.load_config(project_slug)


def update_config(project_slug: str, updates: dict) -> dict:
    if not isinstance(updates, dict):
        raise ValueError("config body must be an object")
    with geolib.project_lock(project_slug):
        current = geolib.load_config(project_slug)
        if updates.get("slug", project_slug) != project_slug:
            raise ValueError("project slug cannot be changed")
        current.update(updates)
        current["slug"] = project_slug
        if current.get("market") not in QUESTION_MARKETS:
            raise ValueError("market must be cn, global, or both")
        if "questions" in current:
            current["questions"] = _validated_questions(current["questions"])
        geolib.save_config(project_slug, current)
    return current


def facts_source(project_slug: str) -> dict:
    path = geolib.project_dir(project_slug) / "content" / "facts.md"
    return {"exists": path.exists(), "text": path.read_text("utf-8") if path.exists() else ""}


def save_facts(project_slug: str, text: str):
    with geolib.project_lock(project_slug):
        _write_text(geolib.project_dir(project_slug) / "content" / "facts.md", text)


def asset_tree(project_slug: str):
    import dashboard

    return dashboard.asset_tree(project_slug)


def read_asset(project_slug: str, relative: str):
    import dashboard

    return dashboard.read_asset(project_slug, relative)


def save_asset(project_slug: str, relative: str, text: str):
    base = geolib.project_dir(project_slug) / "assets"
    target = _safe_target(base, relative, TEXT_SUFFIXES)
    if not target.is_file():
        raise FileNotFoundError(relative)
    with geolib.project_lock(project_slug):
        _write_text(target, text)


def workbench(project_slug: str, question_id: str):
    import dashboard

    if question_id and not re.fullmatch(r"q\d{3,6}", question_id):
        raise ValueError("invalid question id")
    return dashboard.workbench(project_slug, question_id)


def precheck(text: str):
    import analytics

    return analytics.precheck(text)


def factcheck(project_slug: str):
    return geolib.read_json(geolib.project_dir(project_slug) / "factcheck.json", []) or []


def save_factcheck(project_slug: str, items: list):
    if len(items) > 1000 or any(not isinstance(item, dict) for item in items):
        raise ValueError("factcheck items must contain at most 1000 objects")
    with geolib.project_lock(project_slug):
        geolib.write_json(geolib.project_dir(project_slug) / "factcheck.json", items)


def update_distribution(project_slug: str, question_id: str, channel: str, enabled: bool):
    question_id = question_id.strip()
    channel = channel.strip()
    if not question_id or len(question_id) > 64 or not channel or len(channel) > 256:
        raise ValueError("question id and channel are required")
    path = geolib.project_dir(project_slug) / "distribution.json"
    with geolib.project_lock(project_slug):
        distribution = geolib.read_json(path, {}) or {}
        if enabled:
            distribution.setdefault(question_id, {})[channel] = geolib.now_iso()
        else:
            distribution.get(question_id, {}).pop(channel, None)
            if not distribution.get(question_id):
                distribution.pop(question_id, None)
        geolib.write_json(path, distribution)
    return distribution


def read_content(project_slug: str, relative: str | None = None):
    base = geolib.project_dir(project_slug) / "content"
    if not relative:
        return {"files": sorted(path.name for path in base.glob("*.md")) if base.exists() else []}
    target = _safe_target(base, relative, {".md"})
    if not target.is_file():
        raise FileNotFoundError(relative)
    return {"path": relative, "text": target.read_text("utf-8", errors="replace")}


def save_content(project_slug: str, relative: str, text: str):
    if "/" in relative or "\\" in relative or ".." in relative or relative.startswith("."):
        raise ValueError("content filename must not contain a path")
    target = _safe_target(geolib.project_dir(project_slug) / "content", relative, {".md"})
    with geolib.project_lock(project_slug):
        _write_text(target, text)


def expansion(project_slug: str):
    return geolib.read_json(geolib.project_dir(project_slug) / "expand.json", {}) or {}


def add_questions(project_slug: str, items: list):
    if not items or len(items) > 200 or any(not isinstance(item, dict) for item in items):
        raise ValueError("question candidates must contain 1 to 200 objects")
    with geolib.project_lock(project_slug):
        config = geolib.load_config(project_slug)
        questions = config.setdefault("questions", [])
        existing = {str(question.get("text") or "").strip() for question in questions}
        series = {"cn": 1, "global": 101, "both": 901}
        used = {
            int(match.group(1))
            for question in questions
            if (match := re.fullmatch(r"q(\d+)", str(question.get("id") or "")))
        }
        added = []
        for item in items:
            text = str(item.get("text") or "").strip()
            market = item.get("market") if item.get("market") in series else "cn"
            group = str(item.get("group") or "场景").strip() or "场景"
            if not text or len(text) > 1000 or text in existing:
                continue
            number = series[market]
            while number in used:
                number += 1
            used.add(number)
            question = {
                "id": f"q{number:03d}",
                "group": group,
                "market": market,
                "text": text,
                "source": "expand",
            }
            questions.append(question)
            existing.add(text)
            added.append(question)
        if added:
            geolib.save_config(project_slug, config)
    return added


def project_files(project_slug: str):
    directory = geolib.project_dir(project_slug)

    def names(subdirectory, pattern="*"):
        path = directory / subdirectory
        return sorted((item.name for item in path.glob(pattern)), reverse=True) if path.exists() else []

    deliverables = directory / "deliverables"
    content = directory / "content"
    return {
        "reports": [name for name in names("reports") if name.startswith("2")],
        "deliveries": [name for name in names("delivery") if name.startswith("2")],
        "samples": names("samples", "*.md"),
        "deliverables": sorted(path.name for path in deliverables.glob("*.html")) if deliverables.exists() else [],
        "content": sorted(path.name for path in content.glob("*.md")) if content.exists() else [],
    }
