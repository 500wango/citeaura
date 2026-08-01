"""为引擎管线产物附加展示层语言字段，不改写原始 tasks.json。"""

TASK_TEXT = {
    "统一一句话定义，四处逐字一致": {
        "en": "Standardize the one-sentence definition across four surfaces",
        "ja": "4 つの掲載面で一文の定義を統一",
    },
    "建品牌事实卡并标注证据等级": {
        "en": "Build a brand facts library with evidence grades",
        "ja": "証拠レベル付きのブランドファクトライブラリを作成",
    },
    "修复前端渲染空壳页（SSR / 预渲染）": {
        "en": "Fix client-rendered empty-shell pages (SSR / prerender)",
        "ja": "クライアント描画の空シェルページを修正（SSR / プリレンダー）",
    },
    "全站补 JSON-LD 结构化数据": {
        "en": "Add JSON-LD structured data site-wide",
        "ja": "サイト全体に JSON-LD 構造化データを追加",
    },
    "全站补「数字事实」抽取块": {"en": "Add numeric-facts extraction blocks site-wide", "ja": "サイト全体に数値ファクト抽出ブロックを追加"},
    "全站补「FAQ」抽取块": {"en": "Add FAQ extraction blocks site-wide", "ja": "サイト全体に FAQ 抽出ブロックを追加"},
    "全站补「定义」抽取块": {"en": "Add definition extraction blocks site-wide", "ja": "サイト全体に定義抽出ブロックを追加"},
    "全站补「对比」抽取块": {"en": "Add comparison extraction blocks site-wide", "ja": "サイト全体に比較抽出ブロックを追加"},
    "全站补「操作步骤」抽取块": {"en": "Add step-by-step extraction blocks site-wide", "ja": "サイト全体に手順抽出ブロックを追加"},
    "核心页正文扩到 1000+ 词": {"en": "Expand core-page body copy to 1,000+ words", "ja": "主要ページ本文を 1,000 語以上に拡張"},
    "百科词条（实体消歧地基）": {"en": "Create an encyclopedia entry for entity disambiguation", "ja": "エンティティ曖昧性解消の百科事典項目を作成"},
    "上线 /llms.txt 官方事实索引": {"en": "Publish the official facts index at /llms.txt", "ja": "公式ファクト索引を /llms.txt に公開"},
    "建英文原生内容区": {"en": "Build English-native content pages", "ja": "英語ネイティブのコンテンツページを構築"},
}
FIELD_TEXT = {
    "内容矩阵": {"en": "Content matrix", "ja": "コンテンツマトリクス"},
    "实体消歧": {"en": "Entity disambiguation", "ja": "エンティティ曖昧性解消"},
    "知识库": {"en": "Knowledge base", "ja": "ナレッジベース"},
    "页面技术": {"en": "Page technology", "ja": "ページ技術"},
    "外部证据": {"en": "External evidence", "ja": "外部エビデンス"},
    "监测闭环": {"en": "Measurement loop", "ja": "測定ループ"},
    "内容": {"en": "Content", "ja": "コンテンツ"},
    "开发": {"en": "Engineering", "ja": "開発"},
    "市场": {"en": "Marketing", "ja": "マーケティング"},
    "GEO顾问": {"en": "GEO strategist", "ja": "GEO ストラテジスト"},
    "未分配": {"en": "Unassigned", "ja": "未割り当て"},
}


def localize_ticket(ticket):
    """复制工单并附加展示层语言字段，原字段保持与引擎契约一致。"""
    result = dict(ticket)
    title = ticket.get("title")
    for locale in ("en", "ja"):
        result[f"title_{locale}"] = TASK_TEXT.get(title, {}).get(locale, title)
        for field in ("package", "owner"):
            value = ticket.get(field)
            result[f"{field}_{locale}"] = FIELD_TEXT.get(value, {}).get(locale, value)
    return result


def localize_tickets(tickets):
    return [localize_ticket(ticket) if isinstance(ticket, dict) else ticket for ticket in tickets]
