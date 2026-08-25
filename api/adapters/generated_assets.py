"""Project-language contract for engine-generated workspace assets."""

import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from api.adapters import brand_facts, delivery
from api.adapters.engine import geolib


TEXT_SUFFIXES = frozenset((".txt", ".json", ".html", ".md"))
INTERNAL_PATHS = frozenset((
    ".citeaura-manual-edits.json",
    "index.json",
    "outlines/_index.json",
    "outlines/index.json",
    "drafts/_lint.json",
))
LANGUAGE_VARIANT_PATTERN = re.compile(r"(?:^|\.)(?:zh|cn)(?:\.|$)", re.IGNORECASE)
QUESTION_ASSET_PATTERN = re.compile(r"^(?:outlines|drafts)/(q\d{3,6})\.md$")
PLACEHOLDER_PATTERN = re.compile(r"\[(?:Add|Insert|Replace|Verify)[^\]]*\]|\b(?:TODO|TBD)\b", re.IGNORECASE)
CONTRACT = "citeaura.generated-assets.v1"
MANUAL_EDITS_CONTRACT = "citeaura.manual-asset-edits.v1"
FACT_DERIVED_ASSET_PATHS = frozenset((
    "llms.txt",
    "llms.en.txt",
    "snippets/definition.en.html",
))


def language_violation(value):
    return delivery._contains_disallowed_english(value)


def _language_variant(relative):
    return any(LANGUAGE_VARIANT_PATTERN.search(part) for part in Path(relative).parts)


def validate_asset_text(text):
    if language_violation(text):
        raise ValueError("asset text must be written in English and use English typography")
    return str(text or "")


def validate_asset_path(relative):
    relative = str(relative or "").strip().replace("\\", "/")
    path = Path(relative)
    if not relative or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError("invalid asset path")
    if language_violation(relative) or _language_variant(relative):
        raise ValueError("asset path must use the English workspace contract")
    if relative in INTERNAL_PATHS:
        raise ValueError("generated asset indexes cannot be edited")
    return relative


def _atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(text, "utf-8")
    os.replace(temporary, path)


def _manual_edits_path(project_slug):
    return geolib.project_dir(project_slug) / "assets" / ".citeaura-manual-edits.json"


def _manual_edit_paths(project_slug):
    value = geolib.read_json(_manual_edits_path(project_slug), {}) or {}
    if value.get("contract") != MANUAL_EDITS_CONTRACT:
        return []
    return [
        str(relative).strip().replace("\\", "/")
        for relative in value.get("paths") or []
        if str(relative or "").strip()
    ]


def mark_manual_edit(project_slug, relative):
    relative = validate_asset_path(relative)
    with geolib.project_lock(project_slug):
        paths = _manual_edit_paths(project_slug)
        if relative not in paths:
            paths.append(relative)
        payload = {
            "contract": MANUAL_EDITS_CONTRACT,
            "paths": sorted(paths),
        }
        _atomic_write(_manual_edits_path(project_slug), json.dumps(payload, indent=2) + "\n")


@contextmanager
def preserve_manual_asset_edits(project_slug):
    """Restore user-saved English assets after an engine generation pass."""
    project = geolib.project_dir(project_slug)
    assets = project / "assets"
    paths = _manual_edit_paths(project_slug)
    if not assets.is_dir() or not paths:
        yield
        return

    snapshot = Path(tempfile.mkdtemp(prefix=".manual-assets-", dir=project))
    try:
        preserved = []
        base = assets.resolve()
        for relative in paths:
            source = (assets / relative).resolve()
            try:
                source.relative_to(base)
            except ValueError:
                continue
            if not source.is_file() or source.is_symlink():
                continue
            text = source.read_text("utf-8", errors="replace")
            if language_violation(text):
                continue
            target = snapshot / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            preserved.append(relative)
        try:
            yield
        finally:
            for relative in preserved:
                source = snapshot / relative
                target = assets / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    finally:
        shutil.rmtree(snapshot, ignore_errors=True)


def _safe_blueprint(config, blueprint):
    existing = {
        str(item.get("id")): item
        for item in (blueprint.get("contents") if isinstance(blueprint, dict) else []) or []
        if isinstance(item, dict) and item.get("id")
    }
    contents = []
    for question in config.get("questions") or []:
        if not isinstance(question, dict):
            continue
        question_id = str(question.get("id") or "").strip()
        text = str(question.get("text") or "").strip()
        if not re.fullmatch(r"q\d{3,6}", question_id) or not text or language_violation(text):
            continue
        previous = existing.get(question_id, {})
        group = str(question.get("group") or previous.get("group") or "recommendation").strip()
        form = str(previous.get("form") or "Definition or guide page").strip()
        if language_violation(group):
            group = "recommendation"
        if language_violation(form):
            form = "Definition or guide page"
        contents.append({
            **previous,
            "id": question_id,
            "market": "global",
            "group": group,
            "question": text,
            "form": form,
        })
    return {"contents": contents}


def _relative_projection_path(path, destination):
    relative = Path(path)
    if relative.parts and relative.parts[0] == "assets":
        relative = Path(*relative.parts[1:])
    return destination / relative


def _copy_replacement(source, target, migrated):
    if not source.is_file():
        return
    text = source.read_text("utf-8")
    if language_violation(text):
        return
    if target.is_file():
        current = target.read_text("utf-8", errors="replace")
        if not language_violation(current):
            return
    _atomic_write(target, text)
    migrated.append(target)


def _normalize_drafts(assets, active_ids, migrated):
    drafts = assets / "drafts"
    if not drafts.is_dir():
        return
    for path in sorted(drafts.glob("*.md")):
        if re.fullmatch(r"q\d{3,6}", path.stem) and path.stem not in active_ids:
            continue
        current = path.read_text("utf-8", errors="replace")
        normalized = delivery.normalize_generated_draft_text(current)
        if normalized != current and not language_violation(normalized):
            _atomic_write(path, normalized)
            migrated.append(path)


def _hidden_reason(relative, path, active_ids, omitted_schema):
    if relative in INTERNAL_PATHS:
        return "internal"
    if _language_variant(relative):
        return "language_variant"
    if language_violation(relative):
        return "language_contract"
    match = QUESTION_ASSET_PATTERN.fullmatch(relative)
    if match and match.group(1) not in active_ids:
        return "inactive_question"
    if relative in omitted_schema:
        return "unsupported_schema"
    try:
        text = path.read_text("utf-8")
    except UnicodeDecodeError:
        return "language_contract"
    if language_violation(text):
        return "language_contract"
    return None


def _visible_assets(assets, active_ids, omitted_schema, review_schema=None, facts_review_pending=False):
    records = []
    excluded = {}
    for path in sorted(assets.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        relative = path.relative_to(assets).as_posix()
        reason = _hidden_reason(relative, path, active_ids, omitted_schema)
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        text = path.read_text("utf-8", errors="replace")
        issues = []
        status = "draft" if relative.startswith(("drafts/", "outlines/")) else "deployable"
        if relative in (review_schema or set()):
            status = "review_required"
            issues.append("schema_applicability_requires_review")
        if facts_review_pending and (
            relative in FACT_DERIVED_ASSET_PATHS or relative.startswith("jsonld/")
        ) and status == "deployable":
            status = "review_required"
            issues.append("derived_from_unreviewed_brand_facts")
        if PLACEHOLDER_PATTERN.search(text):
            status = "review_required" if status == "deployable" else status
            issues.append("contains_incomplete_material")
        question_id = None
        question_match = QUESTION_ASSET_PATTERN.fullmatch(relative)
        if question_match:
            question_id = question_match.group(1)
        fact_derived = relative in FACT_DERIVED_ASSET_PATHS or relative.startswith("jsonld/")
        if status == "draft":
            workflow_status = "draft"
        elif facts_review_pending and fact_derived:
            workflow_status = "facts_required"
        elif status == "review_required":
            workflow_status = "evidence_required" if "contains_incomplete_material" in issues else "review"
        else:
            workflow_status = "deployable"
        records.append({
            "path": relative,
            "size": path.stat().st_size,
            "group": relative.split("/", 1)[0] if "/" in relative else "Root",
            "status": status,
            "issues": issues,
            "workflow_status": workflow_status,
            "question_id": question_id,
            "facts_required": bool(fact_derived and facts_review_pending),
            "evidence_required": bool(status == "review_required" and not (fact_derived and facts_review_pending)),
            "review_required": status == "review_required",
        })
    return records, excluded


def _write_index(assets, records, excluded):
    path = assets / "index.json"
    current = geolib.read_json(path, {}) or {}
    payload = {
        "contract": CONTRACT,
        "language": "English",
        "market": "global",
        "assets": [record["path"] for record in records],
        "asset_records": records,
        "deployable_assets": [record["path"] for record in records if record["status"] == "deployable"],
        "review_required_assets": [record["path"] for record in records if record["status"] == "review_required"],
        "draft_assets": [record["path"] for record in records if record["status"] == "draft"],
        "workflow_summary": {
            stage: sum(record.get("workflow_status") == stage for record in records)
            for stage in ("facts_required", "evidence_required", "draft", "review", "deployable")
        },
        "readiness": ("deployable" if records and all(record["status"] == "deployable" for record in records)
                      else "review_required"),
        "excluded": excluded,
    }
    comparable = {key: value for key, value in current.items() if key != "normalized_at"}
    if comparable == payload:
        return
    payload["normalized_at"] = geolib.now_iso()
    _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def read_project_assets(project_slug, config=None):
    """读取现有资产索引；索引缺失时只在内存中构建最小视图。"""
    project = geolib.project_dir(project_slug)
    assets = project / "assets"
    if not assets.is_dir():
        return {"tree": [], "visible_paths": frozenset(), "excluded": {}}
    index = geolib.read_json(assets / "index.json", {}) or {}
    records = index.get("asset_records") if isinstance(index, dict) else None
    if isinstance(index, dict) and index.get("contract") == CONTRACT and isinstance(records, list):
        records = [item for item in records if isinstance(item, dict) and item.get("path")]
        return {
            "tree": records,
            "visible_paths": frozenset(item["path"] for item in records),
            "excluded": index.get("excluded") if isinstance(index.get("excluded"), dict) else {},
        }
    config = config if isinstance(config, dict) else geolib.load_config(project_slug)
    blueprint = _safe_blueprint(config, geolib.read_json(project / "blueprint.json", {}) or {})
    active_ids = {item["id"] for item in blueprint["contents"]}
    records, excluded = _visible_assets(assets, active_ids, set())
    return {
        "tree": records,
        "visible_paths": frozenset(item["path"] for item in records),
        "excluded": excluded,
    }


def normalize_project_assets(project_slug, config=None):
    """Migrate managed legacy assets and return the safe product-visible tree."""
    project = geolib.project_dir(project_slug)
    assets = project / "assets"
    if not assets.is_dir():
        return {"tree": [], "visible_paths": frozenset(), "migrated": [], "excluded": {}}

    config = config if isinstance(config, dict) else geolib.load_config(project_slug)
    brand_facts.ensure_english_facts(project_slug, config=config)
    audit = geolib.read_json(project / "audit.json", {}) or {}
    blueprint = _safe_blueprint(config, geolib.read_json(project / "blueprint.json", {}) or {})
    active_ids = {item["id"] for item in blueprint["contents"]}
    migrated = []

    with geolib.project_lock(project_slug):
        staging_root = Path(tempfile.mkdtemp(prefix=".assets-english-", dir=project))
        destination = staging_root / "assets"
        try:
            rendered = delivery.render_english_generated_assets(
                project_slug,
                project,
                assets,
                destination,
                config,
                audit,
                blueprint,
                strict=False,
                only_existing=True,
            )

            llms_candidates = (
                destination / "llms.en.txt",
                destination / "drafts" / "llms.en.txt",
            )
            llms_source = next((path for path in llms_candidates if path.is_file()), None)
            if llms_source is not None:
                for filename in ("llms.en.txt", "llms.txt"):
                    target = assets / filename
                    if target.is_file():
                        _copy_replacement(llms_source, target, migrated)

            for rendered_path in rendered["paths"]:
                source = _relative_projection_path(rendered_path, destination)
                relative = source.relative_to(destination)
                if relative.as_posix() in ("llms.en.txt", "drafts/llms.en.txt"):
                    continue
                target = assets / relative
                _copy_replacement(source, target, migrated)

            _normalize_drafts(assets, active_ids, migrated)
            omitted_schema = {
                str(item.get("path") or "")
                for item in rendered["schema_decisions"]
                if item.get("status") == "omitted"
            }
            review_schema = {
                str(item.get("path") or "")
                for item in rendered["schema_decisions"]
                if item.get("status") != "omitted" and item.get("requires_review")
            }
            facts_path = project / "content" / "facts.md"
            facts_review_pending = facts_path.is_file() and not brand_facts.publication_approved(
                project_slug, facts_path.read_text("utf-8"),
            )
            records, excluded = _visible_assets(
                assets, active_ids, omitted_schema, review_schema,
                facts_review_pending=facts_review_pending,
            )
            _write_index(assets, records, excluded)
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)

    return {
        "tree": records,
        "visible_paths": frozenset(record["path"] for record in records),
        "migrated": [path.relative_to(assets).as_posix() for path in migrated],
        "excluded": excluded,
    }
