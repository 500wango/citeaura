"""站外实体人工复核清单，文件是唯一事实源。"""
import hashlib, ipaddress, json, re
from datetime import datetime, timezone
from urllib.parse import urlparse
from api.adapters.engine import geolib

FIXED = [("official_site", "official site"), ("wikipedia_wikidata", "Wikipedia/Wikidata"), ("linkedin", "LinkedIn"), ("x", "X"), ("facebook_instagram", "Facebook/Instagram"), ("google_business", "Google Business")]
def _valid(url):
    p = urlparse(str(url or ""))
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password or len(str(url)) > 2048 or re.search(r"[\x00-\x1f\x7f]", str(url)): raise ValueError("invalid entity URL")
    host = p.hostname.lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")): raise ValueError("private entity URL not allowed")
    try:
        address = ipaddress.ip_address(host)
        if not address.is_global: raise ValueError("private entity URL not allowed")
    except ValueError as exc:
        if str(exc) == "private entity URL not allowed": raise
    return str(url)
def load(project_slug, citation_domains=None):
    path = geolib.project_dir(project_slug) / "offsite_entities.json"
    tombstone_path = path.with_name("offsite_entities.tombstones.json")
    tombstones = set()
    if tombstone_path.is_file():
        try:
            stored = json.loads(tombstone_path.read_text("utf-8")) or []
            tombstones = {str(item.get("id")) if isinstance(item, dict) else str(item) for item in stored}
        except (OSError, ValueError): tombstones = set()
    if path.is_file():
        try: return json.loads(path.read_text("utf-8"))
        except (OSError, ValueError): return []
    now = datetime.now(timezone.utc).isoformat()
    items = [{"id": i, "platform": p, "url": "", "status": "pending", "evidence_url": None, "reviewer_note": "", "updated_at": now, "source": "fixed"} for i,p in FIXED]
    for domain in (citation_domains or [])[:2]:
        dynamic_id = "domain_" + hashlib.sha256(domain.encode()).hexdigest()[:12]
        if dynamic_id in tombstones: continue
        items.append({"id": dynamic_id, "platform": "directory", "url": "https://" + domain, "status": "pending", "evidence_url": None, "reviewer_note": "", "updated_at": now, "source": "citation"})
    return items
def save(project_slug, items):
    normalized=[]
    for item in items:
        if not isinstance(item, dict): continue
        row=dict(item); row["status"] = row.get("status", "pending")
        if row["status"] not in ("pending", "consistent", "needs_fix"): raise ValueError("invalid entity status")
        if row.get("url"): _valid(row["url"])
        if row.get("evidence_url"): _valid(row["evidence_url"])
        source = row.get("source")
        fixed_ids = {item_id: platform for item_id, platform in FIXED}
        if source == "fixed" and (row.get("id") not in fixed_ids or row.get("platform") != fixed_ids[row.get("id")]): raise ValueError("invalid fixed entity")
        if source == "citation" and not re.fullmatch(r"domain_[a-f0-9]{12}", str(row.get("id") or "")): raise ValueError("invalid citation entity")
        if source == "custom" and row.get("platform") != "custom": raise ValueError("custom entity must use custom platform")
        row["updated_at"] = datetime.now(timezone.utc).isoformat(); normalized.append(row)
    path = geolib.project_dir(project_slug) / "offsite_entities.json"
    tombstone_path = path.with_name("offsite_entities.tombstones.json")
    previous = []
    if path.is_file():
        try: previous = json.loads(path.read_text("utf-8")) or []
        except (OSError, ValueError): previous = []
    tombstones = []
    if tombstone_path.is_file():
        try: tombstones = json.loads(tombstone_path.read_text("utf-8")) or []
        except (OSError, ValueError): tombstones = []
    tombstone_ids = {str(item.get("id")) if isinstance(item, dict) else str(item) for item in tombstones}
    current_ids = {str(item.get("id")) for item in normalized}
    for item in previous:
        item_id = str(item.get("id")) if isinstance(item, dict) else ""
        if item_id.startswith("domain_") and item_id not in current_ids and item_id not in tombstone_ids:
            tombstones.append({"id": item_id, "item": item, "deleted_at": datetime.now(timezone.utc).isoformat()})
    with geolib.project_lock(project_slug):
        geolib.write_json(path, normalized); geolib.write_json(tombstone_path, tombstones)
    return normalized

def restore(project_slug, entity_id):
    """清除指定动态实体 tombstone，下一次读取可重新派生。"""
    path = geolib.project_dir(project_slug) / "offsite_entities.tombstones.json"
    if not path.is_file(): return False
    try: tombstones = json.loads(path.read_text("utf-8")) or []
    except (OSError, ValueError): tombstones = []
    match = next((item for item in tombstones if (str(item.get("id")) if isinstance(item, dict) else str(item)) == str(entity_id)), None)
    if match is None: return False
    remaining = [item for item in tombstones if item is not match]
    list_path = geolib.project_dir(project_slug) / "offsite_entities.json"
    try: items = json.loads(list_path.read_text("utf-8")) or []
    except (OSError, ValueError): items = []
    restored = dict(match.get("item") or {}) if isinstance(match, dict) else {}
    if restored and not any(str(item.get("id")) == str(entity_id) for item in items if isinstance(item, dict)):
        restored["updated_at"] = datetime.now(timezone.utc).isoformat(); items.append(restored)
    with geolib.project_lock(project_slug):
        geolib.write_json(list_path, items); geolib.write_json(path, remaining)
    return True

def deleted(project_slug):
    path = geolib.project_dir(project_slug) / "offsite_entities.tombstones.json"
    if not path.is_file(): return []
    try: rows = json.loads(path.read_text("utf-8")) or []
    except (OSError, ValueError): return []
    return [{"id": str(row.get("id")), "platform": (row.get("item") or {}).get("platform", "directory"), "url": (row.get("item") or {}).get("url", ""), "deleted_at": row.get("deleted_at")} for row in rows if isinstance(row, dict)]
