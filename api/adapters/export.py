"""面向外部报表的稳定 CSV 渲染。"""

import csv
import io


FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _cell(value):
    """把以 =/+/−/@ 开头的单元格中和掉，避免 CSV 被 Excel 当公式执行。"""
    text = "" if value is None else str(value)
    if text.startswith(FORMULA_PREFIXES):
        return "'" + text
    return text


def report_csv(project_slug, report):
    """把产品报告转成不含密钥的平面表格。"""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([
        "project", "date", "provider", "model_id", "sampling_mode", "sample_count",
        "mention_rate", "mention_interval", "median_rank", "citation_share",
    ])
    for item in report.get("engines") or []:
        interval = item.get("mention_interval") or {}
        writer.writerow([
            _cell(project_slug),
            _cell(report.get("date") or ""),
            _cell(item.get("provider_name") or item.get("engine_name") or item.get("engine_code") or ""),
            _cell(item.get("model_id") or ""),
            _cell(item.get("sampling_mode") or ""),
            item.get("sample_count") or 0,
            item.get("mention_rate") if item.get("mention_rate") is not None else "",
            f"{interval.get('lower')}..{interval.get('upper')}" if interval else "",
            item.get("median_rank") if item.get("median_rank") is not None else "",
            item.get("citation_share") if item.get("citation_share") is not None else "",
        ])
    writer.writerow([])
    writer.writerow(["citation_source", "mentions", "question_count", "observed_in"])
    for item in report.get("channels") or []:
        writer.writerow([
            _cell(item.get("domain") or ""),
            item.get("count") or 0,
            item.get("question_count") or 0,
            _cell(", ".join(item.get("engines") or [])),
        ])
    return output.getvalue().encode("utf-8-sig")
