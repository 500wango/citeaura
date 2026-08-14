"""引擎工作台文件接口的租户内适配。"""

import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse

from api.adapters.engine import geolib
from api.adapters.exceptions import GeoEngineError
from api.adapters import brand_facts, brand_identity, competitor_scope, generated_assets, global_scope


TEXT_SUFFIXES = {".txt", ".json", ".html", ".md"}


def _usable_crawl_pages(project_slug: str):
    path = geolib.project_dir(project_slug) / "evidence" / "pages.jsonl"
    pages = geolib.read_jsonl(path)
    usable = [
        page for page in pages
        if isinstance(page, dict) and page.get("status") == 200 and str(page.get("text") or "").strip()
    ]
    return pages, usable


def _visible_snapshot_text(path: Path):
    if not path.is_file():
        return ""
    soup = geolib.parse_html(path.read_text("utf-8", errors="replace"))
    return " ".join(geolib.main_text(soup).split())[:20000]


def _metadata_text(page: dict):
    """正文缺失时提取仍可由服务端验证的页面元数据。"""
    values = [page.get("title"), page.get("meta_description")]
    values.extend(page.get("h1") or [])
    values.extend(page.get("h2") or [])

    def collect_jsonld(value):
        if isinstance(value, dict):
            for key in ("name", "headline", "description", "alternateName"):
                item = value.get(key)
                if isinstance(item, str):
                    values.append(item)
                elif isinstance(item, list):
                    values.extend(entry for entry in item if isinstance(entry, str))
            for item in value.values():
                if isinstance(item, (dict, list)):
                    collect_jsonld(item)
        elif isinstance(value, list):
            for item in value:
                collect_jsonld(item)

    collect_jsonld(page.get("jsonld_raw") or [])
    unique = []
    seen = set()
    for value in values:
        value = " ".join(str(value or "").split())
        if value and value not in seen:
            unique.append(value)
            seen.add(value)
    return "\n".join(unique)[:20000]


def _set_page_text(page: dict, text: str):
    text = str(text or "").strip()[:20000]
    if not text:
        return False
    page["text"] = text
    page["word_count"] = geolib.word_count(text)
    page["language"] = geolib.page_language(text, page.get("lang", ""))
    page["cjk_ratio"] = geolib.cjk_ratio(text)
    return True


def _recover_snapshot_text(project_slug: str):
    project_dir = geolib.project_dir(project_slug)
    snapshot_dir = (project_dir / "evidence" / "html").resolve()
    path = project_dir / "evidence" / "pages.jsonl"
    pages = geolib.read_jsonl(path)
    recovered = 0
    for page in pages:
        if not isinstance(page, dict) or page.get("status") != 200 or str(page.get("text") or "").strip():
            continue
        snapshot = str(page.get("snapshot") or "").strip()
        text = ""
        if snapshot:
            snapshot_path = (project_dir / snapshot).resolve()
            try:
                snapshot_path.relative_to(snapshot_dir)
            except ValueError:
                snapshot_path = None
            if snapshot_path is not None and snapshot_path.suffix.lower() == ".html":
                text = _visible_snapshot_text(snapshot_path)
        if _set_page_text(page, text or _metadata_text(page)):
            recovered += 1
    if recovered:
        geolib.write_jsonl(path, pages)
    return recovered


def _create_identity_evidence(project_slug: str):
    """纯客户端站点无正文时，以用户确认的项目身份建立最小基线。"""
    project_dir = geolib.project_dir(project_slug)
    path = project_dir / "evidence" / "pages.jsonl"
    pages = geolib.read_jsonl(path)
    config = geolib.read_json(project_dir / "geo.json", {})
    brand = config.get("brand") or {}
    name = str(brand.get("name") or "").strip()
    site = str(brand.get("site") or "").strip()
    if not name or not site:
        return 0
    text = (
        f"Brand: {name}\n"
        f"Official website: {site}\n"
        "The website returned no server-rendered page text during this crawl."
    )
    for page in pages:
        if isinstance(page, dict) and page.get("status") == 200:
            if _set_page_text(page, text):
                geolib.write_jsonl(path, pages)
                return 1
    return 0


@contextmanager
def resilient_crawl_evidence(project_slug: str):
    """Autopilot 抓取正文为空时恢复快照文本或沿用上一份有效证据。"""
    import crawl as engine_crawl

    project_dir = geolib.project_dir(project_slug)
    evidence_dir = project_dir / "evidence"
    _, previous_usable = _usable_crawl_pages(project_slug)
    site_path = evidence_dir / "site.json"
    previous_site = geolib.read_json(site_path, None)
    config = geolib.read_json(project_dir / "geo.json", {}) or {}
    configured_site = str(((config.get("brand") or {}).get("site")) or "").rstrip("/")
    evidence_site = str((previous_site or {}).get("root") or "").rstrip("/")
    same_site_evidence = not configured_site or not evidence_site or configured_site == evidence_site
    if not same_site_evidence:
        previous_usable, previous_site = [], None
    original_run = engine_crawl.run

    with tempfile.TemporaryDirectory(prefix=f"citeaura-crawl-{project_slug}-") as temporary:
        backup_dir = Path(temporary) / "evidence"
        if evidence_dir.is_dir() and same_site_evidence:
            shutil.copytree(evidence_dir, backup_dir)

        def restore_previous_evidence():
            if not backup_dir.is_dir():
                return
            if evidence_dir.exists():
                shutil.rmtree(evidence_dir)
            shutil.copytree(backup_dir, evidence_dir)

        def normalized_result(result):
            normalized = global_scope.deduplicate_crawl_evidence(project_slug)
            if isinstance(result, dict) and normalized.get("site"):
                fields = {
                    key: value for key, value in normalized["site"].items()
                    if key in ("pages_crawled", "pages_ok", "pages_crawled_raw", "duplicate_pages_removed")
                }
                return {**result, **fields}
            return result

        def run_with_recovery(slug, *args, **kwargs):
            if slug != project_slug:
                return original_run(slug, *args, **kwargs)
            try:
                result = original_run(slug, *args, **kwargs)
            except Exception:
                restore_previous_evidence()
                raise
            _, current_usable = _usable_crawl_pages(project_slug)
            if current_usable:
                return normalized_result(result)
            recovered = _recover_snapshot_text(project_slug)
            if recovered:
                geolib.info(f"Recovered extractable text from {recovered} crawl page(s) using snapshots or metadata")
                return normalized_result(result)
            if previous_usable:
                restore_previous_evidence()
                geolib.info("Current crawl returned no extractable text; retained previous usable crawl evidence")
                return normalized_result(previous_site or result)
            if _create_identity_evidence(project_slug):
                geolib.info(
                    "Website returned no server-rendered text; continuing with project identity only. "
                    "The crawl audit will report the missing content."
                )
                return normalized_result(result)
            raise GeoEngineError(
                "Crawl completed but no extractable website text was found. "
                "The site may require JavaScript rendering or block automated crawlers."
            )

        engine_crawl.run = run_with_recovery
        try:
            yield
        finally:
            engine_crawl.run = original_run


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
        market = item.get("market", "global")
        group = str(item.get("group") or "Recommendation").strip() or "Recommendation"
        if not re.fullmatch(r"q\d{3,6}", qid) or qid in used_ids:
            raise ValueError("question ids must be unique qNNN values")
        if not text or len(text) > 1000:
            raise ValueError("question text is required and must not exceed 1000 characters")
        if global_scope.contains_han(text):
            raise ValueError("question text must not contain Chinese characters")
        if market != "global":
            raise ValueError("question market must be global")
        validated.append({**item, "id": qid, "text": text, "market": "global", "group": group})
        used_ids.add(qid)
    return validated


def read_config(project_slug: str) -> dict:
    return ensure_global_engine_scope(project_slug)


def ensure_global_engine_scope(project_slug: str) -> dict:
    """把历史项目及已有产物归一为国际市场。"""
    return global_scope.normalize_project(project_slug)


def update_config(project_slug: str, updates: dict) -> dict:
    if not isinstance(updates, dict):
        raise ValueError("config body must be an object")
    if "publishing" in updates:
        raise ValueError("publishing config must use the publishing API")
    if "competitors" in updates:
        updates = {**updates, "competitors": competitor_scope.normalize_user_competitors(updates["competitors"])}
    with geolib.project_lock(project_slug):
        current = global_scope.normalize_config_data(geolib.load_config(project_slug))
        previous_site = str((current.get("brand") or {}).get("site") or "").rstrip("/")
        if updates.get("slug", project_slug) != project_slug:
            raise ValueError("project slug cannot be changed")
        current.update(updates)
        current["slug"] = project_slug
        current["market"] = "global"
        if "url" in updates:
            current.setdefault("brand", {})["site"] = updates["url"]
        if "questions" in current:
            current["questions"] = _validated_questions(current["questions"])
        current = global_scope.normalize_config_data(current)
        geolib.save_config(project_slug, current)
        current_site = str((current.get("brand") or {}).get("site") or "").rstrip("/")
        if previous_site and current_site and previous_site != current_site:
            shutil.rmtree(geolib.project_dir(project_slug) / "evidence", ignore_errors=True)
    return global_scope.normalize_project(project_slug)


def facts_source(project_slug: str) -> dict:
    path = geolib.project_dir(project_slug) / "content" / "facts.md"
    migration = brand_facts.ensure_english_facts(project_slug)
    text = path.read_text("utf-8") if path.exists() else ""
    return {
        "exists": path.exists(),
        "text": brand_facts.display_text(text),
        "language": "non_english" if brand_facts.contains_han(text) else "en",
        "migration": migration,
    }


def save_facts(project_slug: str, text: str):
    with geolib.project_lock(project_slug):
        _write_text(
            geolib.project_dir(project_slug) / "content" / "facts.md",
            brand_facts.reviewed_text(text),
        )


def asset_tree(project_slug: str):
    config = ensure_global_engine_scope(project_slug)
    return generated_assets.normalize_project_assets(project_slug, config=config)["tree"]


def read_asset(project_slug: str, relative: str):
    relative = generated_assets.validate_asset_path(relative)
    config = ensure_global_engine_scope(project_slug)
    state = generated_assets.normalize_project_assets(project_slug, config=config)
    if relative not in state["visible_paths"]:
        raise FileNotFoundError(relative)
    target = _safe_target(geolib.project_dir(project_slug) / "assets", relative, TEXT_SUFFIXES)
    if not target.is_file():
        raise FileNotFoundError(relative)
    return {"path": relative, "text": target.read_text("utf-8")}


def save_asset(project_slug: str, relative: str, text: str):
    relative = generated_assets.validate_asset_path(relative)
    text = generated_assets.validate_asset_text(text)
    config = ensure_global_engine_scope(project_slug)
    state = generated_assets.normalize_project_assets(project_slug, config=config)
    if relative not in state["visible_paths"]:
        raise FileNotFoundError(relative)
    base = geolib.project_dir(project_slug) / "assets"
    target = _safe_target(base, relative, TEXT_SUFFIXES)
    if not target.is_file():
        raise FileNotFoundError(relative)
    with geolib.project_lock(project_slug):
        _write_text(target, text)
    generated_assets.mark_manual_edit(project_slug, relative)
    generated_assets.normalize_project_assets(project_slug, config=config)


def workbench(project_slug: str, question_id: str):
    import dashboard

    if question_id and not re.fullmatch(r"q\d{3,6}", question_id):
        raise ValueError("invalid question id")
    config = ensure_global_engine_scope(project_slug)
    result = dashboard.workbench(project_slug, question_id)
    sample_directory = geolib.project_dir(project_slug) / "samples"
    files = sorted(sample_directory.glob("*.jsonl")) if sample_directory.exists() else []
    rows = geolib.read_jsonl(files[-1]) if files else []
    result["samples"] = [
        {
            "engine_code": row.get("platform"),
            "engine_name": row.get("platform_name") or row.get("platform"),
            "question_id": row.get("question_id"),
            "question": row.get("question"),
            "answer": row.get("answer"),
            "ok": bool(row.get("ok")),
            "error": row.get("error"),
            "mentioned": bool((row.get("analysis") or {}).get("brand_mentioned")),
            "rank": (row.get("analysis") or {}).get("brand_rank"),
            "matched_identity": (row.get("analysis") or {}).get("matched_identity"),
            "citations": row.get("citations") or [],
            "sampling_mode": "Manual - Product interface" if row.get("sample_mode") == "manual" or row.get("terminal") == "web" else (
                "API - Search grounded" if row.get("search_enabled") else "API - Parametric knowledge"
            ),
            "sampled_at": row.get("ts"),
        }
        for row in rows
        if global_scope.is_global_sample(row) and brand_identity.is_current_sample(row, config)
        if not question_id or row.get("question_id") == question_id
    ]
    result["sample_date"] = files[-1].stem if files else None
    return result


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
        original = geolib.load_config(project_slug)
        config = global_scope.normalize_config_data(original)
        questions = config.setdefault("questions", [])
        existing = {str(question.get("text") or "").strip() for question in questions}
        used = {
            int(match.group(1))
            for question in questions
            if (match := re.fullmatch(r"q(\d+)", str(question.get("id") or "")))
        }
        added = []
        for item in items:
            text = str(item.get("text") or "").strip()
            market = item.get("market", "global")
            group = str(item.get("group") or "Scenario").strip() or "Scenario"
            if not text or len(text) > 1000:
                raise ValueError("question text is required and must not exceed 1000 characters")
            if global_scope.contains_han(text):
                raise ValueError("question text must not contain Chinese characters")
            if market != "global":
                raise ValueError("question market must be global")
            if text in existing:
                continue
            number = 101
            while number in used:
                number += 1
            used.add(number)
            question = {
                "id": f"q{number:03d}",
                "group": group,
                "market": "global",
                "text": text,
                "source": "expand",
            }
            questions.append(question)
            existing.add(text)
            added.append(question)
        if added or config != original:
            geolib.save_config(project_slug, config)
    if added or config != original:
        global_scope.normalize_project(project_slug)
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


def _merge_ticket_workflow(project_slug: str, workflow_tickets: list[dict]):
    """把用户维护的负责人、期限和时间线合并回重建后的工单。"""
    if not workflow_tickets:
        return None
    import tasks as engine_tasks

    fields = (
        "status", "closed_at", "owner", "due_date", "notes", "activity", "evidence", "workflow_customized",
    )
    by_id = {item.get("id"): item for item in workflow_tickets if item.get("id")}
    by_title = {item.get("title"): item for item in workflow_tickets if item.get("title")}
    with geolib.project_lock(project_slug):
        data = engine_tasks.load(project_slug)
        current = data.get("tasks") if isinstance(data.get("tasks"), list) else []
        changed = False
        for ticket in current:
            previous = by_id.get(ticket.get("id")) or by_title.get(ticket.get("title"))
            if previous is None:
                continue
            for field in fields:
                if field in previous and ticket.get(field) != previous.get(field):
                    ticket[field] = deepcopy(previous.get(field))
                    changed = True
        if changed:
            engine_tasks.save(project_slug, data)
    return data


@contextmanager
def preserve_manual_tickets(project_slug: str):
    """引擎重建计划时保留 SaaS 创建的 offsite 工单。"""
    import tasks as engine_tasks

    data = engine_tasks.load(project_slug)
    tickets = data.get("tasks", []) if isinstance(data, dict) else []
    manual_tickets = [deepcopy(ticket) for ticket in tickets if _is_manual_offsite(ticket)]
    workflow_tickets = [deepcopy(ticket) for ticket in tickets if ticket.get("workflow_customized")]
    if not manual_tickets and not workflow_tickets:
        yield
        return

    original_build = engine_tasks.build

    def build_with_manual(slug):
        rebuilt = original_build(slug)
        if slug == project_slug:
            _merge_manual_tickets(project_slug, manual_tickets)
            return _merge_ticket_workflow(project_slug, workflow_tickets) or rebuilt
        return rebuilt

    engine_tasks.build = build_with_manual
    try:
        yield
    finally:
        engine_tasks.build = original_build
        _merge_manual_tickets(project_slug, manual_tickets)
        _merge_ticket_workflow(project_slug, workflow_tickets)


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

    config = global_scope.normalize_project(project_slug)
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
            "package": "External Evidence",
            "market": "global",
            "kind": "offsite",
            "source": "manual",
            "title": f"Promote {hostname} page to enrich brand facts",
            "why": f"This external page influences AI search citations across {len(question_ids)} target user questions. First-party verifiable evidence is required.",
            "action": f"Contact site owner with update request: {ask_text}",
            "owner": "Marketing",
            "effort": "M",
            "window": "60d",
            "url": url,
            "ask_text": ask_text,
            "influenced_questions": question_ids,
            "influenced_question_texts": question_texts,
            "affected": [],
            "acceptance": {
                "type": "manual",
                "desc": "Manually verify the external page has been updated with requested facts, and attach URL or outreach log in ticket evidence.",
            },
            "status": "todo",
            "assets": [],
            "evidence": [],
            "closed_at": None,
        }
        tickets.append(ticket)
        data.setdefault("slug", project_slug)
        data.setdefault("generated_at", geolib.now_iso())
        data["market"] = "global"
        data.setdefault("baseline", {})
        data["tasks"] = tickets
        engine_tasks.save(project_slug, data)
    return ticket


def import_sample_sheet(project_slug: str, filename: str, text: str):
    """保存并导入项目内的人工产品端采样表。"""
    filename = str(filename or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}-manual\.md", filename):
        raise ValueError("sample sheet filename must be YYYY-MM-DD-manual.md")
    if not isinstance(text, str) or len(text) > 5_000_000:
        raise ValueError("sample sheet must not exceed 5000000 characters")

    import sample
    from api.adapters import measurement

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
        metrics = sample.sample_import(project_slug, str(target))
        measurement.record_sampling(project_slug, source="manual", requested_platforms=platforms)
    global_scope.normalize_project(project_slug)
    return metrics


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
