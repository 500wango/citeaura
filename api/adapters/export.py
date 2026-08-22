"""面向外部报表的稳定 CSV 渲染。"""

import csv
import io


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
            project_slug,
            report.get("date") or "",
            item.get("provider_name") or item.get("engine_name") or item.get("engine_code") or "",
            item.get("model_id") or "",
            item.get("sampling_mode") or "",
            item.get("sample_count") or 0,
            item.get("mention_rate") if item.get("mention_rate") is not None else "",
            f"{interval.get('low')}..{interval.get('high')}" if interval else "",
            item.get("median_rank") if item.get("median_rank") is not None else "",
            item.get("citation_share") if item.get("citation_share") is not None else "",
        ])
    writer.writerow([])
    writer.writerow(["citation_source", "mentions", "question_count", "observed_in"])
    for item in report.get("channels") or []:
        writer.writerow([
            item.get("domain") or "",
            item.get("count") or 0,
            item.get("question_count") or 0,
            ", ".join(item.get("engines") or []),
        ])
    return output.getvalue().encode("utf-8-sig")
