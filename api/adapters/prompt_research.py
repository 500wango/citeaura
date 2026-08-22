"""Seed/URL based prompt research for the workspace question workflow."""

import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from api.adapters.engine import geolib


INTENTS = (
    ("recommendation", "Discovery", "What are the best {seed} options for a growing team?"),
    ("comparison", "Evaluation", "How does {seed} compare with the leading alternatives?"),
    ("alternative", "Evaluation", "What are the best alternatives to {seed}?"),
    ("pricing", "Evaluation", "How much does {seed} cost and is it worth it?"),
    ("use_case", "Decision", "How do teams use {seed} in practice?"),
    ("risk", "Decision", "What should buyers verify before choosing {seed}?"),
)


def _clean_seed(value):
    value = re.sub(r"\s+", " ", str(value or "").strip())
    return value[:160]


def _site_seed(url):
    host = (urlparse(str(url or "")).hostname or "").lower().removeprefix("www.")
    return host.split(".", 1)[0].replace("-", " ") if host else ""


def _item_id(seed, intent):
    digest = hashlib.sha1(f"{seed}:{intent}".encode("utf-8")).hexdigest()[:12]
    return f"research-{digest}"


def research(project_slug, seeds=None, url=None):
    """Generate bounded candidates without sampling or changing the stable bank."""
    cfg = geolib.read_json(geolib.project_dir(project_slug) / "geo.json", {}) or {}
    brand = cfg.get("brand") or {}
    values = list(seeds or [])
    values.extend([
        brand.get("name"),
        brand.get("industry"),
        *[item.get("name") for item in cfg.get("competitors") or [] if isinstance(item, dict)],
        *[item for item in brand.get("products") or []],
    ])
    values.insert(0, _site_seed(url or brand.get("site")))
    unique = []
    seen = set()
    for value in values:
        seed = _clean_seed(value)
        key = seed.casefold()
        if len(seed) < 2 or key in seen:
            continue
        seen.add(key)
        unique.append(seed)
        if len(unique) >= 12:
            break

    existing = {
        str(item.get("text") or "").strip().casefold()
        for item in cfg.get("questions") or []
        if isinstance(item, dict)
    }
    items = []
    fanout = []
    for seed in unique:
        queries = []
        for intent, funnel_stage, template in INTENTS:
            text = template.format(seed=seed)
            query = text.rstrip("?")
            queries.append(query)
            items.append({
                "id": _item_id(seed, intent),
                "text": text,
                "seed": seed,
                "intent": intent,
                "funnel_stage": funnel_stage,
                "source": "seed/url research",
                "in_question_bank": text.casefold() in existing,
            })
        fanout.append({"seed": seed, "queries": queries})

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_url": url or brand.get("site"),
        "seeds": unique,
        "fanout": fanout,
        "items": items[:72],
        "candidate_count": min(len(items), 72),
    }
    geolib.write_json(geolib.project_dir(project_slug) / "prompt_research.json", result)
    return result


def read(project_slug):
    return geolib.read_json(geolib.project_dir(project_slug) / "prompt_research.json", {}) or {}
