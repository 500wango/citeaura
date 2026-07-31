"""引擎工作台文件接口的租户内适配。"""

import os
import re
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse

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
    return ensure_all_engine_scope(project_slug)


def ensure_all_engine_scope(project_slug: str) -> dict:
    """把历史项目归一为全引擎范围，保留问题级语言路由。"""
    with geolib.project_lock(project_slug):
        current = geolib.load_config(project_slug)
        if current.get("market") != "both":
            current["market"] = "both"
            geolib.save_config(project_slug, current)
    return current


def update_config(project_slug: str, updates: dict) -> dict:
    if not isinstance(updates, dict):
        raise ValueError("config body must be an object")
    with geolib.project_lock(project_slug):
        current = geolib.load_config(project_slug)
        if updates.get("slug", project_slug) != project_slug:
            raise ValueError("project slug cannot be changed")
        current.update(updates)
        current["slug"] = project_slug
        current["market"] = "both"
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


def _is_manual_offsite(ticket: dict) -> bool:
    return ticket.get("source") == "manual" and ticket.get("kind") == "offsite"


def _merge_manual_tickets(project_slug: str, manual_tickets: list[dict]):
    """把 SaaS 手工工单合并回引擎生成的 tasks.json。"""
    if not manual_tickets:
        return None
    import tasks as engine_tasks

    with geolib.project_lock(project_slug):
        data = engine_tasks.load(project_slug)
        if not isinstance(data, dict):
            data = {}
        current = data.get("tasks") if isinstance(data.get("tasks"), list) else []
        current_manual_ids = {
            ticket.get("id") for ticket in current if _is_manual_offsite(ticket)
        }
        missing = [ticket for ticket in manual_tickets if ticket.get("id") not in current_manual_ids]
        if not missing:
            return data
        merged = current + deepcopy(missing)
        data["tasks"] = merged
        engine_tasks.save(project_slug, data)
    return data


@contextmanager
def preserve_manual_tickets(project_slug: str):
    """引擎重建计划时保留 SaaS 创建的 offsite 工单。"""
    import tasks as engine_tasks

    data = engine_tasks.load(project_slug)
    tickets = data.get("tasks", []) if isinstance(data, dict) else []
    manual_tickets = [deepcopy(ticket) for ticket in tickets if _is_manual_offsite(ticket)]
    if not manual_tickets:
        yield
        return

    original_build = engine_tasks.build

    def build_with_manual(slug):
        rebuilt = original_build(slug)
        if slug == project_slug:
            return _merge_manual_tickets(project_slug, manual_tickets)
        return rebuilt

    engine_tasks.build = build_with_manual
    try:
        yield
    finally:
        engine_tasks.build = original_build
        _merge_manual_tickets(project_slug, manual_tickets)


def create_offsite_ticket(project_slug: str, url: str, ask_text: str, influenced_questions: list[str]):
    """创建需人工验收的外部页面工单并写入 tasks.json。"""
    url = str(url or "").strip()
    parsed = urlparse(url)
    if len(url) > 2048 or parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("url must be a valid http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError("url must not contain credentials")
    url = url.rstrip("/")

    ask_text = str(ask_text or "").strip()
    if not ask_text or len(ask_text) > 5000:
        raise ValueError("ask_text is required and must not exceed 5000 characters")
    if not isinstance(influenced_questions, list) or not 1 <= len(influenced_questions) <= 200:
        raise ValueError("influenced_questions must contain 1 to 200 question ids")

    config = geolib.load_config(project_slug)
    question_by_id = {
        str(question.get("id") or ""): question
        for question in config.get("questions", [])
        if isinstance(question, dict) and question.get("id")
    }
    question_ids = []
    for raw_id in influenced_questions:
        question_id = str(raw_id or "").strip()
        if question_id not in question_by_id:
            raise ValueError(f"unknown influenced question: {question_id}")
        if question_id not in question_ids:
            question_ids.append(question_id)
    if not question_ids:
        raise ValueError("at least one influenced question is required")

    import tasks as engine_tasks

    with geolib.project_lock(project_slug):
        data = engine_tasks.load(project_slug)
        if not isinstance(data, dict):
            data = {}
        tickets = data.get("tasks") if isinstance(data.get("tasks"), list) else []
        if len(tickets) >= 5000:
            raise ValueError("ticket limit reached")
        used = {
            int(match.group(1))
            for ticket in tickets
            if (match := re.fullmatch(r"M-(\d{3,6})", str(ticket.get("id") or "")))
        }
        number = 1
        while number in used:
            number += 1
        ticket_id = f"M-{number:03d}"
        question_texts = [str(question_by_id[qid].get("text") or qid) for qid in question_ids]
        hostname = parsed.hostname.lower()
        ticket = {
            "id": ticket_id,
            "priority": "P1",
            "package": "外部证据",
            "market": config.get("market", "both"),
            "kind": "offsite",
            "source": "manual",
            "title": f"推动 {hostname} 页面补充品牌信息",
            "why": f"该外部页面会影响 {len(question_ids)} 个用户问题的检索与引用，需要补充可核验的一手信息。",
            "action": f"联系页面负责人并提出更新诉求：{ask_text}",
            "owner": "市场",
            "effort": "M",
            "window": "60天",
            "url": url,
            "ask_text": ask_text,
            "influenced_questions": question_ids,
            "influenced_question_texts": question_texts,
            "affected": [],
            "acceptance": {
                "type": "manual",
                "desc": "人工确认外站已按诉求更新，并在工单证据中记录页面链接或沟通结果",
            },
            "status": "todo",
            "assets": [],
            "evidence": [],
            "closed_at": None,
        }
        tickets.append(ticket)
        data.setdefault("slug", project_slug)
        data.setdefault("generated_at", geolib.now_iso())
        data.setdefault("market", config.get("market", "both"))
        data.setdefault("baseline", {})
        data["tasks"] = tickets
        engine_tasks.save(project_slug, data)
    return ticket


def import_sample_sheet(project_slug: str, filename: str, text: str):
    """保存并导入项目内的人工网页端采样表。"""
    filename = str(filename or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}-manual\.md", filename):
        raise ValueError("sample sheet filename must be YYYY-MM-DD-manual.md")
    if not isinstance(text, str) or len(text) > 5_000_000:
        raise ValueError("sample sheet must not exceed 5000000 characters")

    import sample

    platforms = re.findall(r"(?m)^##\s+platform:\s*(\S+)\s*$", text)
    allowed_platforms = set(sample.PROVIDERS) | set(sample.MANUAL_ONLY)
    invalid_platforms = sorted(set(platforms) - allowed_platforms)
    if not platforms or invalid_platforms:
        detail = ", ".join(invalid_platforms) if invalid_platforms else "none"
        raise ValueError(f"sample sheet contains invalid platforms: {detail}")

    config = geolib.load_config(project_slug)
    known_questions = {
        str(question.get("id") or "")
        for question in config.get("questions", [])
        if isinstance(question, dict)
    }
    sheet_questions = set(re.findall(r"(?m)^###\s+(\S+)\s*·", text))
    unknown_questions = sorted(sheet_questions - known_questions)
    if not sheet_questions or unknown_questions:
        detail = ", ".join(unknown_questions) if unknown_questions else "none"
        raise ValueError(f"sample sheet contains invalid questions: {detail}")

    target = _safe_target(geolib.project_dir(project_slug) / "samples", filename, {".md"})
    if not target.is_file():
        raise FileNotFoundError(filename)
    with geolib.project_lock(project_slug):
        _write_text(target, text)
        return sample.sample_import(project_slug, str(target))


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
