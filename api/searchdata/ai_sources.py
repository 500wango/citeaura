"""带版本号的 AI 助手来源域名表：GA4 sessionSource 归一化与分类。"""

from urllib.parse import urlsplit


# 任何域名或引擎映射的变更都必须同时 bump 版本号；快照会记录本次使用的版本。
TABLE_VERSION = "2026-10-30.1"

# (domain, engine_code, engine_name)，按 domain 升序且唯一；单测强制约束。
AI_SOURCES = (
    ("bard.google.com", "gemini", "Google Gemini"),
    ("chat.baidu.com", "ernie", "文心一言"),
    ("chat.deepseek.com", "deepseek", "DeepSeek"),
    ("chat.mistral.ai", "mistral", "Mistral Le Chat"),
    ("chat.openai.com", "openai", "ChatGPT"),
    ("chat.zhipuai.cn", "zhipu", "智谱清言"),
    ("chatglm.cn", "zhipu", "智谱清言"),
    ("chatgpt.com", "openai", "ChatGPT"),
    ("claude.ai", "claude", "Claude"),
    ("copilot.microsoft.com", "copilot", "Microsoft Copilot"),
    ("deepseek.com", "deepseek", "DeepSeek"),
    ("doubao.com", "doubao", "豆包"),
    ("gemini.google.com", "gemini", "Google Gemini"),
    ("grok.com", "grok", "Grok"),
    ("hailuoai.com", "minimax", "海螺 AI"),
    ("kimi.com", "kimi", "Kimi"),
    ("kimi.moonshot.cn", "kimi", "Kimi"),
    ("meta.ai", "meta", "Meta AI"),
    ("metaso.cn", "metaso", "秘塔 AI 搜索"),
    ("notebooklm.google.com", "gemini", "Google NotebookLM"),
    ("perplexity.ai", "perplexity", "Perplexity"),
    ("poe.com", "poe", "Poe"),
    ("qianwen.com", "qwen", "通义千问"),
    ("qwen.ai", "qwen", "Qwen"),
    ("tongyi.aliyun.com", "qwen", "通义千问"),
    ("wenxin.baidu.com", "ernie", "文心一言"),
    ("yiyan.baidu.com", "ernie", "文心一言"),
    ("you.com", "you", "You.com"),
    ("yuanbao.tencent.com", "yuanbao", "腾讯元宝"),
    ("z.ai", "zhipu", "Z.ai"),
)

_INDEX = {domain: (engine_code, engine_name) for domain, engine_code, engine_name in AI_SOURCES}
# 最长后缀优先，避免将来加入较宽的域名时抢先匹配。
_ORDERED = tuple(sorted((domain for domain, _, _ in AI_SOURCES), key=len, reverse=True))

_PLACEHOLDERS = frozenset(("", "(not set)", "(direct)", "(none)", "direct", "none", "not set"))


def normalize_host(value):
    """把 GA4 的 sessionSource 或 URL 归一化成裸主机名。"""
    text = str(value or "").strip().casefold()
    if text in _PLACEHOLDERS:
        return None
    if "://" not in text:
        text = "//" + text
    try:
        host = urlsplit(text).hostname or ""
    except ValueError:
        return None
    host = host.strip().strip(".").casefold()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def classify(source):
    """按最长后缀把来源归到 AI 引擎；无法识别返回 None。"""
    host = normalize_host(source)
    if not host:
        return None
    for domain in _ORDERED:
        if host == domain or host.endswith("." + domain):
            engine_code, engine_name = _INDEX[domain]
            return {
                "source": host,
                "rule": domain,
                "engine_code": engine_code,
                "engine_name": engine_name,
            }
    return None


def table_info():
    return {"version": TABLE_VERSION, "domain_count": len(AI_SOURCES)}
