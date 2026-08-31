"""Render raw answer evidence and comparable before/after delivery artifacts."""

import csv
import html
import io
import json
from pathlib import Path

from api.adapters import brand_identity, global_scope
from api.adapters.delivery_language import _contains_disallowed_english
from api.adapters.exceptions import GeoEngineError


def _mode(row):
    if row.get("sample_mode") == "manual" or row.get("terminal") in ("web", "manual"):
        return "Manual - Product interface"
    if row.get("search_enabled"):
        return "API - Search grounded"
    return "API - Parametric knowledge"


def _rows(path, config):
    rows = []
    for row in _read_jsonl(path):
        if not isinstance(row, dict):
            continue
        if global_scope.is_global_sample(row, config) and brand_identity.is_current_sample(row, config):
            rows.append(row)
    return rows


def _read_jsonl(path):
    try:
        return [json.loads(line) for line in Path(path).read_text("utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        raise GeoEngineError(f"delivery evidence source is invalid: {path.name}") from exc


def _english(value, field):
    text = str(value or "").strip()
    if _contains_disallowed_english(text):
        raise GeoEngineError(f"delivery evidence cannot be represented in English: {field}")
    return text


def _citation_items(citations):
    result = []
    for item in citations or []:
        if isinstance(item, str):
            result.append({"url": _english(item, "citation URL")})
        elif isinstance(item, dict) and item.get("url"):
            result.append({
                key: _english(item[key], f"citation {key}")
                for key in ("url", "title", "domain") if item.get(key)
            })
    return result


def _record(row, run_id):
    analysis = row.get("analysis") if isinstance(row.get("analysis"), dict) else {}
    answer = _english(row.get("answer"), "raw answer")
    question = _english(row.get("question") or row.get("question_id"), "question")
    platform = _english(row.get("platform_name") or row.get("platform"), "platform")
    model = _english(row.get("raw_model"), "model")
    citations = _citation_items(row.get("citations"))
    return {
        "run_id": run_id,
        "date": _english(row.get("date"), "sample date"),
        "ts": _english(row.get("ts"), "sample timestamp"),
        "platform": platform,
        "model": model,
        "sampling_mode": _mode(row),
        "question_set_id": _english(row.get("question_set_id"), "question set"),
        "cohort_id": _english(row.get("cohort_id"), "cohort"),
        "question_id": _english(row.get("question_id"), "question id"),
        "question": question,
        "answer": answer,
        "citations": citations,
        "brand_mentioned": bool(analysis.get("brand_mentioned")),
        "official_domain_cited": bool(analysis.get("own_domain_cited")),
        "competitors_mentioned": [
            _english(item, "competitor") for item in analysis.get("competitors_mentioned") or []
        ],
        "ok": bool(row.get("ok")),
    }


def _jsonl(records):
    return "".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in records)


def _evidence_html(name, records):
    rows = []
    for record in records:
        citations = "<br>".join(html.escape(item.get("url", "")) for item in record["citations"]) or "None"
        rows.append(
            "<article class='evidence'>"
            f"<h2>{html.escape(record['platform'])} · {html.escape(record['model'] or 'Model not recorded')}</h2>"
            f"<p class='meta'>{html.escape(record['sampling_mode'])} · {html.escape(record['date'])} · {html.escape(record['question_id'] or 'Question not recorded')}</p>"
            f"<p><strong>Question</strong><br>{html.escape(record['question'])}</p>"
            f"<pre>{html.escape(record['answer'])}</pre>"
            f"<p><strong>Citations</strong><br>{citations}</p>"
            f"<p class='meta'>Mentioned: {str(record['brand_mentioned']).lower()} · Official domain cited: {str(record['official_domain_cited']).lower()}</p>"
            "</article>"
        )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(name)} Raw AI Answer Evidence</title><style>"
        "body{font:15px/1.6 system-ui,sans-serif;max-width:960px;margin:0 auto;padding:32px;color:#17221d;background:#f5f8f6}"
        "h1{font-size:28px}.evidence{background:#fff;border:1px solid #dbe6e0;border-radius:8px;padding:20px;margin:20px 0}"
        ".meta{color:#62716a;font-size:13px}pre{white-space:pre-wrap;background:#eef3ef;border:1px solid #dbe6e0;padding:14px;border-radius:6px}"
        "</style></head><body><h1>Raw AI Answer Evidence</h1>"
        f"<p>{len(records)} filtered sample records from the current delivery cycle.</p>{''.join(rows)}</body></html>"
    )


def _citation_csv(records):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Run ID", "Question ID", "Platform", "Model", "Sampling Mode", "Question", "Citation URL", "Citation Title"])
    for record in records:
        for citation in record["citations"] or [{}]:
            writer.writerow([
                record["run_id"], record["question_id"], record["platform"], record["model"],
                record["sampling_mode"], record["question"], citation.get("url", ""), citation.get("title", ""),
            ])
    return output.getvalue()


def _group_key(row):
    return (
        str(row.get("platform") or ""), str(row.get("raw_model") or ""), _mode(row),
        str(row.get("question_id") or row.get("question") or ""),
    )


def _rate(rows, field):
    return sum(bool((row.get("analysis") or {}).get(field)) for row in rows) / len(rows) if rows else None


def _delta_markdown(name, before_name, after_name, before, after):
    before_keys = {_group_key(row) for row in before}
    after_keys = {_group_key(row) for row in after}
    comparable = bool(before and after and before_keys == after_keys)
    lines = [f"# {name} Before / After Visibility Delta", ""]
    if not comparable:
        lines += [
            "## Comparison unavailable for this cycle", "",
            "A comparable post-change run is required before reporting a before/after delta.", "",
            f"- Before samples: {before_name} ({len(before)})",
            f"- After samples: {after_name} ({len(after)})",
            "- Required match: same questions, providers, models, and sampling modes.", "",
        ]
        return "\n".join(lines), False
    before_by = {}
    after_by = {}
    for row in before:
        before_by.setdefault(_group_key(row), []).append(row)
    for row in after:
        after_by.setdefault(_group_key(row), []).append(row)
    lines += [
        "## Comparable measurement", "",
        f"- Before run: `{before_name}` ({len(before)} samples)",
        f"- After run: `{after_name}` ({len(after)} samples)",
        "- Cohort policy: same question IDs, providers, models, and sampling modes.", "",
        "| Provider | Model | Mode | Question | Mention before | Mention after | Citation before | Citation after |",
        "|---|---|---|---|---:|---:|---:|---:|",
    ]
    for key in sorted(before_by):
        platform, model, mode, question = key
        b_rows, a_rows = before_by[key], after_by[key]
        lines.append(
            f"| {platform} | {model or 'Not recorded'} | {mode} | {question} | "
            f"{_rate(b_rows, 'brand_mentioned'):.1%} | {_rate(a_rows, 'brand_mentioned'):.1%} | "
            f"{_rate(b_rows, 'own_domain_cited'):.1%} | {_rate(a_rows, 'own_domain_cited'):.1%} |"
        )
    return "\n".join(lines), True


def write_evidence(project_directory, config, destination, name):
    """Write raw answer evidence and a truthful before/after report."""
    samples = Path(project_directory) / "samples"
    files = sorted(samples.glob("*.jsonl")) if samples.is_dir() else []
    current = files[-1] if files else None
    current_rows = _rows(current, config) if current else []
    records = [_record(row, current.stem if current else "Not recorded") for row in current_rows]
    evidence_dir = Path(destination) / "07-Evidence"
    delta_dir = Path(destination) / "08-Before-After"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    delta_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "raw-ai-answers.jsonl").write_text(_jsonl(records), "utf-8")
    (evidence_dir / "raw-ai-answers.html").write_text(_evidence_html(name, records), "utf-8")
    (evidence_dir / "citation-evidence.csv").write_text(_citation_csv(records), "utf-8")
    before = _rows(files[-2], config) if len(files) > 1 else []
    after = current_rows
    delta, comparable = _delta_markdown(name, files[-2].stem if len(files) > 1 else "Not available", current.stem if current else "Not available", before, after)
    (delta_dir / "visibility-delta.md").write_text(delta, "utf-8")
    import report
    (delta_dir / "visibility-delta.html").write_text(
        report.build_html(f"{name} Before / After Visibility Delta", delta, [("Comparable", "Yes" if comparable else "No")]),
        "utf-8",
    )
    return {
        "records": len(records),
        "comparable": comparable,
        "files": [
            "07-Evidence/raw-ai-answers.jsonl", "07-Evidence/raw-ai-answers.html", "07-Evidence/citation-evidence.csv",
            "08-Before-After/visibility-delta.md", "08-Before-After/visibility-delta.html",
        ],
    }
