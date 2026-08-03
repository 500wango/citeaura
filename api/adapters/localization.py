"""为引擎管线产物附加展示层语言字段，不改写原始 tasks.json。"""

from api.i18n import DEFAULT_LOCALE, resolve

# 中文 id 仅作消息键；展示回退走 api/i18n（en 优先，不再把中文当源语言特权）。
TASK_IDS = (
    "统一一句话定义，四处逐字一致",
    "建品牌事实卡并标注证据等级",
    "修复前端渲染空壳页（SSR / 预渲染）",
    "全站补 JSON-LD 结构化数据",
    "全站补「数字事实」抽取块",
    "全站补「FAQ」抽取块",
    "全站补「定义」抽取块",
    "全站补「对比」抽取块",
    "全站补「操作步骤」抽取块",
    "核心页正文扩到 1000+ 词",
    "百科词条（实体消歧地基）",
    "上线 /llms.txt 官方事实索引",
    "建英文原生内容区",
)
FIELD_IDS = (
    "内容矩阵",
    "实体消歧",
    "知识库",
    "页面技术",
    "外部证据",
    "监测闭环",
    "内容",
    "开发",
    "市场",
    "GEO顾问",
    "未分配",
)


def _localized(value, locale):
    if value is None:
        return value
    text = resolve(value, locale)
    # 非 zh 且解析仍等于中文键时，再试 en，避免把中文当展示回退
    if locale != "zh" and text == value:
        english = resolve(value, DEFAULT_LOCALE)
        if english != value:
            return english
    return text


def localize_ticket(ticket):
    """复制工单并附加展示层语言字段，原字段保持与引擎契约一致。"""
    result = dict(ticket)
    title = ticket.get("title")
    for locale in ("en", "ja"):
        result[f"title_{locale}"] = _localized(title, locale)
        for field in ("package", "owner"):
            value = ticket.get(field)
            result[f"{field}_{locale}"] = _localized(value, locale)
    return result


def localize_tickets(tickets):
    return [localize_ticket(ticket) if isinstance(ticket, dict) else ticket for ticket in tickets]
