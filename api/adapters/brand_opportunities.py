"""从现有事实库、问题库和采样回答生成需人工复核的机会。"""

import re

from api.adapters.engine import geolib


def _latest(directory, pattern="*.jsonl"):
    files = sorted(directory.glob(pattern)) if directory.exists() else []
    return files[-1] if files else None


def _facts(text):
    return [line.strip(" -*") for line in str(text or "").splitlines() if line.strip().startswith(("-", "*")) and len(line.strip(" -*")) >= 12]


def assess(project_slug):
    directory = geolib.project_dir(project_slug)
    facts_path = directory / "content" / "facts.md"
    facts_text = facts_path.read_text(encoding="utf-8") if facts_path.is_file() else ""
    claims = _facts(facts_text)
    sample_path = _latest(directory / "samples")
    rows = [row for row in geolib.read_jsonl(sample_path)] if sample_path else []
    answers = [str(row.get("answer") or row.get("response") or row.get("text") or "") for row in rows if row.get("ok")]
    conflicts = []
    for claim in claims:
        words = [word for word in re.findall(r"[A-Za-z0-9\u4e00-\u9fff]{4,}", claim) if word.lower() not in {"with", "from", "that", "this", "official"}]
        if not words or not answers:
            continue
        hits = [answer for answer in answers if any(word.casefold() in answer.casefold() for word in words[:4])]
        contradictory = [answer for answer in hits if re.search(r"\b(?:not|never|no|isn't|is not|doesn't|does not)\b", answer, re.I)]
        if contradictory:
            conflicts.append({"type": "potential_conflict", "claim": claim, "status": "needs_review", "evidence": [{"source": "sample", "excerpt": answer[:400]} for answer in contradictory[:3]]})

    opportunities = []
    config = geolib.load_config(project_slug) if directory.exists() else {}
    questions = [item for item in config.get("questions") or [] if isinstance(item, dict)]
    for question in questions:
        text = str(question.get("text") or question.get("question") or "").strip()
        if text and not any(text.casefold() in answer.casefold() for answer in answers):
            opportunities.append({"type": "answer_page", "status": "needs_sampling", "question": text, "suggested_page_type": "FAQ or answer page", "evidence": [{"source": "question_bank", "question_id": question.get("id")}]})
    return {"status": "measured" if answers else "unmeasured", "facts_count": len(claims), "sample_count": len(answers), "conflicts": conflicts, "opportunities": opportunities[:50]}
