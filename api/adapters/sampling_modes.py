"""Sampling-mode codes and canonical labels exposed by the SaaS API.

`sampling_mode` keeps the documented Chinese labels. `sampling_mode_code`
is the stable identifier for UI matching and locale catalogs.
"""

CODE_PARAMETRIC = "parametric"
CODE_SEARCH = "search"
CODE_MANUAL = "manual"

MODE_API = "API·参数化知识"
MODE_SEARCH = "API·联网检索"
MODE_MANUAL = "人工·产品端"

LABEL_BY_CODE = {
    CODE_PARAMETRIC: MODE_API,
    CODE_SEARCH: MODE_SEARCH,
    CODE_MANUAL: MODE_MANUAL,
}


def code_for_provider(provider):
    return CODE_SEARCH if provider.get("search") else CODE_PARAMETRIC


def code_for_row(row):
    if row.get("sample_mode") == "manual" or row.get("terminal") in ("web", "manual"):
        return CODE_MANUAL
    return CODE_SEARCH if row.get("search_enabled") else CODE_PARAMETRIC


def code_for_label(label):
    text = str(label or "")
    lowered = text.lower()
    if text == MODE_MANUAL or "人工" in text or "manual" in lowered or "surface" in lowered:
        return CODE_MANUAL
    if text == MODE_SEARCH or "联网" in text or "search" in lowered or "retrieval" in lowered:
        return CODE_SEARCH
    if text == MODE_API or "参数" in text or "parametric" in lowered or "model knowledge" in lowered:
        return CODE_PARAMETRIC
    return CODE_PARAMETRIC


def for_provider(provider):
    return LABEL_BY_CODE[code_for_provider(provider)]


def for_row(row):
    return LABEL_BY_CODE[code_for_row(row)]


def fields(*, provider=None, row=None, code=None, label=None):
    """Return both the documented label and the stable code."""
    if code is None:
        if row is not None:
            code = code_for_row(row)
        elif provider is not None:
            code = code_for_provider(provider)
        elif label:
            code = code_for_label(label)
        else:
            code = CODE_PARAMETRIC
    return {
        "sampling_mode": LABEL_BY_CODE.get(code, MODE_API),
        "sampling_mode_code": code,
    }
