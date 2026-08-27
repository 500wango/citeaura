"""从现有事实库、问题库和采样回答生成需人工复核的机会。"""

import re
import hashlib

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
    valid_rows = [row for row in rows if row.get("ok") is True and (row.get("search_enabled") is True or str(row.get("sample_mode") or "").lower() in ("manual", "product_surface"))]
    answers = [str(row.get("answer") or row.get("response") or row.get("text") or "") for row in valid_rows]
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
        if not text: continue
        qid = str(question.get("id") or "")
        cohorts = {}
        for row in valid_rows:
            if str(row.get("question_id") or "") != qid: continue
            mode = str(row.get("sampling_mode_code") or ("api_search_grounded" if row.get("search_enabled") else "manual_product_surface"))
            cohorts.setdefault(mode, []).append(row)
        mode, cohort = sorted(cohorts.items(), key=lambda pair: (-len(pair[1]), pair[0]))[0] if cohorts else (None, [])
        mentioned = [row for row in cohort if (row.get("analysis") or {}).get("brand_mentioned") is True]
        gap_type = "not_covered"; status = "not_covered" if len(cohort) >= 3 and not mentioned else "unmeasured"
        target = config.get("mention_rate_target")
        if len(cohort) >= 5 and mentioned and isinstance(target, (int, float)) and len(mentioned) / len(cohort) < target:
            gap_type = status = "low_mention"
        if mentioned and status == "unmeasured": continue
        page_type = "faq"
        evidence = [{"source": "sample", "question_id": qid, "sampling_mode": mode, "excerpt": str(row.get("answer") or row.get("response") or "")[:240]} for row in cohort[:3]] or [{"source": "question_bank", "question_id": qid}]
        opportunities.append({"id": hashlib.sha256(f"{qid}{gap_type}{page_type}".encode()).hexdigest()[:16], "type": "answer_page", "status": status, "question": text, "question_id": qid, "evidence_count": len(evidence) if cohort else 0, "gap_type": gap_type, "suggested_page_type": page_type, "acceptance_criteria": {"type": "verify", "cohort": "same_question_same_sampling_mode", "sampling_mode": mode, "outcomes": ["improved", "unchanged", "regressed", "unmeasured"]}, "evidence": evidence})
    opportunities.sort(key=lambda item: (item.get("question_id", ""), item.get("id", "")))
    return {"status": "measured" if answers else "unmeasured", "facts_count": len(claims), "sample_count": len(answers), "conflicts": conflicts, "opportunities": opportunities[:50]}
