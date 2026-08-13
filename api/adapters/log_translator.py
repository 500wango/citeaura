"""Translate engine runtime logs into English for SaaS presentation without modifying engine/."""

import re

from api.adapters.baseline import normalize_uncertainties

LOG_TRANSLATIONS = [
    (re.compile(r"跳过（缺 API Key）：(.*)"), r"Skipped (Missing API Key): \1"),
    (re.compile(r"\[(.*?)\] (cn|global|both) 市场 · (\d+) 题 × (\d+) 轮"), r"[\1] \2 market · \3 questions × \4 round(s)"),
    (re.compile(r"采样完成：(\d+) 条 → (.*)"), r"Sampling complete: \1 answers collected → \2"),
    (re.compile(r"=== 重抓站点 ==="), r"=== Re-crawling Site ==="),
    (re.compile(r"抓取 (.*?)（上限 (\d+) 页）"), r"Crawling \1 (limit: \2 pages)"),
    (re.compile(r"完成：(\d+)/(\d+) 页可访问 → (.*)"), r"Complete: \1/\2 pages accessible → \3"),
    (re.compile(r"=== 重跑体检 ==="), r"=== Re-running Site Audit ==="),
    (re.compile(r"体检完成：(\d+) 页，均分 ([\d\.]+)，分布 (.*?) → (.*)"), r"Audit complete: \1 pages, avg score \2, grade distribution \3 → \4"),
    (re.compile(r"验收：通过 (\d+) / 未达标 (\d+) / 待人工 (\d+)；状态变更 (\d+) 条"), r"Verification: Passed \1 / Unmet \2 / Manual review \3; Status changed: \4 items"),
    (re.compile(r"推导品牌事实…"), r"Inferring brand facts..."),
    (re.compile(r"设计问题库…"), r"Designing target question bank..."),
    (re.compile(r"推导竞品候选…"), r"Inferring competitor candidates..."),
    (re.compile(r"自动引导：从 (\d+) 字官网正文推导项目底座"), r"Auto-bootstrap: Inferring brand baseline from \1 characters of text"),
    (re.compile(r"生成 (\d+) 项资产 → (.*)"), r"Generated \1 asset(s) → \2"),
    (re.compile(r"三份交付物已生成 → (.*)"), r"Three core deliverables generated → \1"),
    (re.compile(r"交付包已生成 → (.*)"), r"Delivery package compiled → \1"),
    (re.compile(r"错误：抓取失败：没有页面返回 200，检查站点可达性/WAF"), r"Error: Crawl failed: No page returned 200 OK. Check site accessibility or WAF."),
    (re.compile(r"错误：抓取失败：仅 (\d+)/(\d+) 页可访问.*"), r"Error: Crawl failed: Only \1/\2 pages accessible. Check WAF/anti-scraping rules."),
    (re.compile(r"某平台采样中断：(.*)"), r"Engine query interrupted: \1"),
    (re.compile(r"拓词完成：(\d+) 个词根 → (\d+) 条候选"), r"Query expansion complete: \1 root terms → \2 candidates"),
    (re.compile(r"初稿风险检查：(\d+) 项（高风险 (\d+) 项）"), r"Draft risk check: \1 items (High risk: \2 items)"),
    (re.compile(r"═══ 1/8 抓取官网 ═══"), r"═══ 1/8 Crawl Website ═══"),
    (re.compile(r"═══ 2/8 体检 ═══"), r"═══ 2/8 Site Audit ═══"),
    (re.compile(r"═══ 3/8 自动推导品牌事实、竞品与问题库 ═══"), r"═══ 3/8 Bootstrap Baseline & Question Bank ═══"),
    (re.compile(r"═══ 3/8 已有问题库，跳过自动推导 ═══"), r"═══ 3/8 Existing questions found, skipping bootstrap ═══"),
    (re.compile(r"═══ 4/8 AI 答案采样 ═══"), r"═══ 4/8 AI Sampling ═══"),
    (re.compile(r"═══ 5/8 工单与建设蓝图 ═══"), r"═══ 5/8 Action Tickets & Blueprint ═══"),
    (re.compile(r"═══ 6/8 资产与报告 ═══"), r"═══ 6/8 Assets & Diagnostic Report ═══"),
    (re.compile(r"═══ 7/8 三份交付物 ═══"), r"═══ 7/8 Three Core Deliverables ═══"),
    (re.compile(r"═══ 8/8 验收与打包 ═══"), r"═══ 8/8 Verification & Delivery Package ═══"),
    (re.compile(r"跳过：--no-sample"), r"Skipped: --no-sample"),
    (re.compile(r"跳过 (.*?)：问题库里没有 (.*?) 市场的问题"), r"Skipped \1: No questions matching \2 market in question library"),
]


def _translate_manual_input(match):
    values = [item.strip() for item in match.group(1).split(",") if item.strip()]
    normalized = normalize_uncertainties(values)
    return "Needs manual input: " + "; ".join(normalized)


def translate_engine_log(log_text: str) -> str:
    """Translate Chinese engine log output into English."""
    if not log_text:
        return ""
    result = str(log_text)
    for pattern, replacement in LOG_TRANSLATIONS:
        result = pattern.sub(replacement, result)
    result = re.sub(r"(?:Needs manual input|需人工(?:输入|补充))\s*[:：]\s*([^\n]+)", _translate_manual_input, result)
    return result
