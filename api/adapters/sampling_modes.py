"""Sampling-mode labels exposed by the SaaS API."""

MODE_API = "API·参数化知识"
MODE_SEARCH = "API·联网检索"
MODE_MANUAL = "人工·产品端"


def for_provider(provider):
    return MODE_SEARCH if provider.get("search") else MODE_API


def for_row(row):
    if row.get("sample_mode") == "manual" or row.get("terminal") in ("web", "manual"):
        return MODE_MANUAL
    return MODE_SEARCH if row.get("search_enabled") else MODE_API
