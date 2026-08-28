"""Worker 采样产物判定与失败诊断。"""

import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from api.adapters.engine import geolib


class SamplingOutputError(RuntimeError):
    """采样没有产生可度量成功行时，保留可行动的诊断信息。"""

    code = "sampling_no_successful_samples"

    def __init__(self, diagnostic):
        self.diagnostic = diagnostic if isinstance(diagnostic, dict) else {}
        super().__init__(self._format_message())

    def _format_message(self):
        diagnostic = self.diagnostic
        requests = int(diagnostic.get("requests") or 0)
        successful = int(diagnostic.get("successful") or 0)
        failed = int(diagnostic.get("failed") or 0)
        skipped = int(diagnostic.get("skipped") or 0)
        parts = [
            "sampling produced no measurable successful samples",
            f"requests={requests}", f"successful={successful}",
            f"failed={failed}", f"skipped={skipped}",
        ]
        platforms = diagnostic.get("platforms") or []
        if platforms:
            parts.append("platforms=" + ",".join(
                f"{item.get('code')}:{item.get('status')}" for item in platforms[:8]
            ))
        parts.append(f"reason={diagnostic.get('reason') or 'sampling_failed'}")
        parts.append(f"next={diagnostic.get('next_step') or 'check provider configuration and retry'}")
        return "; ".join(parts)


def _latest_metrics_path(project_slug):
    directory = geolib.project_dir(project_slug) / "metrics"
    files = sorted(directory.glob("*.json")) if directory.exists() else []
    return files[-1] if files else None


def _latest_metrics(project_slug):
    path = _latest_metrics_path(project_slug)
    return geolib.read_json(path, {}) if path else {}


def _metrics_written_since(project_slug, started_at):
    if started_at is None:
        return True
    path = _latest_metrics_path(project_slug)
    if path is None:
        return False
    started = started_at if started_at.tzinfo else started_at.replace(tzinfo=timezone.utc)
    written = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return written >= started - timedelta(seconds=5)


def _sample_count(value):
    """把旧产物中的可选计数统一为非负整数。"""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _sampling_success_count(metrics):
    """按明确成功字段优先，兼容历史 metrics 的成功样本口径。"""
    if not isinstance(metrics, dict):
        return 0
    if "successful_sample_count" in metrics:
        return _sample_count(metrics.get("successful_sample_count"))
    summary = metrics.get("sample_summary")
    if isinstance(summary, dict) and "successful" in summary:
        return _sample_count(summary.get("successful"))
    measurement_result = metrics.get("measurement")
    if isinstance(measurement_result, dict) and "effective_samples" in measurement_result:
        return _sample_count(measurement_result.get("effective_samples"))
    platforms = metrics.get("platforms")
    if isinstance(platforms, dict):
        count = sum(_sample_count(item.get("samples")) for item in platforms.values() if isinstance(item, dict))
        if count:
            return count
    observability = metrics.get("provider_observability")
    if isinstance(observability, dict) and "successful" in observability:
        count = _sample_count(observability.get("successful"))
        if count:
            return count
    return _sample_count(metrics.get("sample_count"))


def _sampling_rows(project_slug, metrics):
    """读取本轮 JSONL，诊断时以原始行而不是归一化摘要为准。"""
    directory = geolib.project_dir(project_slug) / "samples"
    if not directory.exists():
        return []
    run_id = metrics.get("run_id") if isinstance(metrics, dict) else None
    if not run_id:
        return []
    path = directory / f"{run_id}.jsonl"
    if not path.is_file():
        return []
    rows = geolib.read_jsonl(path)
    return [row for row in rows if str(row.get("run_id") or "") == str(run_id)]


def _redact_sampling_error(value):
    """保留供应商错误类别，同时避免把响应中的凭据写入 Job 错误。"""
    text = str(value or "").replace("\n", " ").strip()
    text = re.sub(r"(?i)bearer\s+\S+", "Bearer <redacted>", text)
    text = re.sub(r"(?i)(api[_ -]?key|token|secret)([=: ]+)\S+", r"\1\2<redacted>", text)
    return text[:160]


def _sampling_diagnostic(result, project_slug, started_at=None, funding=None):
    """生成不含密钥的采样失败摘要，供日志、Job 和 UI 直接展示。"""
    metrics = result if isinstance(result, dict) else _latest_metrics(project_slug)
    if started_at is not None and not _metrics_written_since(project_slug, started_at):
        metrics = {}
    rows = _sampling_rows(project_slug, metrics)
    summary = metrics.get("sample_summary") if isinstance(metrics, dict) else None
    observability = metrics.get("provider_observability") if isinstance(metrics, dict) else None
    if rows:
        total = len(rows)
        successful = sum(1 for row in rows if row.get("ok"))
        failed = total - successful
    else:
        total = _sample_count((summary or {}).get("total")) if isinstance(summary, dict) else 0
        successful = _sampling_success_count(metrics)
        if not total and isinstance(observability, dict):
            total = _sample_count(observability.get("requests"))
        failed = max(0, total - successful)

    grouped = {}
    for row in rows:
        code = str(row.get("platform") or "unknown")
        item = grouped.setdefault(code, {"successful": 0, "failed": 0, "errors": Counter()})
        if row.get("ok"):
            item["successful"] += 1
        else:
            item["failed"] += 1
            error = _redact_sampling_error(row.get("error"))
            if error:
                item["errors"][error] += 1
    if not grouped and isinstance(summary, dict):
        for code, item in (summary.get("per_platform") or {}).items():
            if isinstance(item, dict):
                grouped[str(code)] = {"successful": _sample_count(item.get("successful")), "failed": _sample_count(item.get("failed")), "errors": Counter()}
    if not grouped and isinstance(observability, dict):
        for code, item in (observability.get("platforms") or {}).items():
            if isinstance(item, dict):
                grouped[str(code)] = {"successful": _sample_count(item.get("successful")), "failed": _sample_count(item.get("failed")), "errors": Counter()}

    try:
        import sample
    except ImportError:
        sample = None
    project_config = geolib.read_json(geolib.project_dir(project_slug) / "geo.json", {})
    configured = [str(code).strip().lower() for code in (project_config.get("platforms") or []) if str(code).strip()]
    has_funding_snapshot = isinstance(funding, dict)
    funded_codes = set()
    if has_funding_snapshot:
        funded_codes.update(str(code).strip().lower() for code in (funding.get("keys") or {}))
        funded_codes.update(str(code).strip().lower() for code in (funding.get("pool_codes") or ()))
    requested = list(dict.fromkeys(code for code in configured if sample is None or code in sample.PROVIDERS or code in funded_codes))
    for code in grouped:
        if code not in requested:
            requested.append(code)

    platform_items = []
    missing_keys = 0
    no_questions = 0
    for code in requested:
        item = grouped.get(code)
        if item and item["successful"]:
            state = "succeeded"
        elif item and item["failed"]:
            error = item["errors"].most_common(1)[0][0] if item["errors"] else "provider_request_failed"
            state = f"failed[{error}]"
        elif has_funding_snapshot and code not in funded_codes:
            state = "missing_worker_funding"
            missing_keys += 1
        elif sample is not None and code in sample.PROVIDERS:
            provider = sample.PROVIDERS[code]
            key_env = provider.get("key_env")
            if not has_funding_snapshot and (not key_env or not os.environ.get(key_env)):
                state = "missing_api_key"
                missing_keys += 1
            else:
                try:
                    matching = sample.questions_for(project_config, code)
                except Exception:  # noqa: BLE001
                    matching = []
                if not matching:
                    state = "no_matching_questions"
                    no_questions += 1
                else:
                    state = "no_successful_samples"
        else:
            state = "no_successful_samples"
        platform_items.append({"code": code, "status": state})

    skipped = sum(1 for item in platform_items if item["status"] in {"missing_worker_funding", "missing_api_key", "no_matching_questions", "no_successful_samples", "not_requested"})
    if not requested and not rows:
        reason, next_step = "no_api_platforms_configured", "configure a funded API key or select Audit only"
    elif requested and not rows and ((has_funding_snapshot and not (funded_codes & set(requested))) or (not has_funding_snapshot and missing_keys == len(requested))):
        reason, next_step = "no_worker_funding", "configure a model key or eligible platform pool, then retry"
    elif no_questions and not rows:
        reason, next_step = "no_matching_questions", "add questions for the configured market, then retry"
    elif total and not successful:
        reason, next_step = "all_requests_failed", "check provider credentials, endpoint, model, and network, then retry"
    else:
        reason, next_step = "no_successful_samples", "check the sampling log and retry"
    return {"requests": total, "successful": successful, "failed": failed, "skipped": skipped, "platforms": platform_items, "reason": reason, "next_step": next_step}


def _sampling_succeeded(result, project_slug, job_id=None, started_at=None):
    if isinstance(result, dict) and not result:
        return False
    if isinstance(result, dict) and result:
        if result.get("run_id"):
            rows = _sampling_rows(project_slug, result)
            if rows:
                return any(bool(row.get("ok")) for row in rows)
        explicit_success = any(key in result for key in ("successful_sample_count", "sample_summary", "measurement", "provider_observability"))
        if explicit_success:
            return _sampling_success_count(result) > 0
        return _sampling_success_count(result) > 0
    if started_at is not None and not _metrics_written_since(project_slug, started_at):
        return False
    metrics = _latest_metrics(project_slug)
    if job_id is not None and started_at is None and str(((metrics or {}).get("provenance") or {}).get("job_id")) != str(job_id):
        return False
    if isinstance(metrics, dict) and metrics.get("run_id"):
        rows = _sampling_rows(project_slug, metrics)
        if rows:
            return any(bool(row.get("ok")) for row in rows)
    return _sampling_success_count(metrics) > 0


def _require_sampling_output(result, project_slug, job_id=None, started_at=None, funding=None):
    if not _sampling_succeeded(result, project_slug, job_id=job_id, started_at=started_at):
        error = SamplingOutputError(_sampling_diagnostic(result, project_slug, started_at=started_at, funding=funding))
        print(f"[citeaura] {error}", flush=True)
        raise error
    return result
