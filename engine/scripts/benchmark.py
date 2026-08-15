"""Compare project-cited domains with the CN-GEO reference ranking.

The compact constants below are derived from ``references/cn-source-ranking.md``
so runtime does not depend on DuckDB or Parquet.
"""

from __future__ import annotations

import math
from numbers import Real

import geolib as G

# High-citation domains covering all 11 platforms in the reference set.
CROSS_PLATFORM = {
    "qq.com": ("Content platform", "Tencent", 11017),
    "toutiao.com": ("Content platform", "ByteDance", 9911),
    "sohu.com": ("General news media", "Sohu", 8000),
    "maigoo.com": ("Commercial recommendations and rankings", "Maigoo", 6741),
    "smzdm.com": ("Interest and lifestyle community", "SMZDM", 6547),
    "163.com": ("General news media", "NetEase", 4777),
    "chinapp.com": ("Commercial recommendations and rankings", "ChinaApp", 3955),
    "cnpp.cn": ("Commercial recommendations and rankings", "", 3429),
    "ctrip.com": ("Local services", "Ctrip", 3273),
    "sina.cn": ("General news media", "Sina", 3112),
    "sina.com.cn": ("General news media", "Sina", 1951),
    "dianping.com": ("Local services", "Dianping", 1895),
    "cnblogs.com": ("Professional technology community", "Cnblogs", 1388),
    "zol.com.cn": ("Professional technology media", "ZOL", 987),
    "36kr.com": ("Business media", "", 969),
}

# Platform ecosystem gateways.
ECOSYSTEM = {
    "baidu.com": ["Baidu AI 37.7%", "ERNIE 29.0%"],
    "sm.cn": ["Qianwen 19.2% (Quark/Sm.cn)"],
    "iesdouyin.com": ["Doubao app 28.1%", "Doubao web 12.0%", "Douyin AI 100%"],
    "toutiao.com": ["Secondary Doubao gateway"],
    "qq.com": ["Yuanbao 20.5%"],
}

# Domains with the strongest average citation placement.
TOP_POSITION = {
    "sm.cn": 5.31, "cnpp.cn": 6.10, "xnnews.com.cn": 6.25, "askci.com": 6.27,
    "maigoo.com": 6.36, "phb123.com": 7.12, "iimedia.cn": 7.27, "uc.cn": 7.32,
    "cnpp100.com": 7.35, "csdn.net": 7.53,
}

# Reference category shares.
CATEGORY_SHARE = [
    ("Content platforms (qq/toutiao/baidu/iesdouyin)", 0.164, 4),
    ("General news media", 0.136, 68),
    ("Commercial recommendation and ranking sites", 0.091, 28),
    ("Local services and user content", 0.052, 23),
    ("Interest and lifestyle communities", 0.038, 8),
    ("Local news media", 0.035, 55),
    ("Government agencies", 0.020, 46),
    ("Official brand and company sites", 0.0137, 52),
]


def _norm(domain: str) -> str:
    return G.normalize_host(domain)


def compare(cited_domains: dict[str, int]) -> dict:
    """Compare ``{domain: citation_count}`` from the current sampling cycle."""
    got: dict[str, Real] = {}
    for domain, count in (cited_domains or {}).items():
        normalized = _norm(domain)
        if (not normalized or isinstance(count, bool) or not isinstance(count, Real)
                or not math.isfinite(count) or count <= 0):
            continue
        got[normalized] = got.get(normalized, 0) + count

    def hit(base: str) -> int:
        """Return current-cycle citations for a domain and its subdomains."""
        return sum(n for d, n in got.items() if d == base or d.endswith("." + base))

    covered, missing = [], []
    for dom, (cat, eco, cit) in sorted(CROSS_PLATFORM.items(), key=lambda x: -x[1][2]):
        n = hit(dom)
        (covered if n else missing).append({
            "domain": dom, "category": cat, "ecosystem": eco,
            "national_citations": cit, "your_citations": n,
        })

    eco_gaps = []
    for dom, notes in ECOSYSTEM.items():
        if not hit(dom):
            eco_gaps.append({"domain": dom, "why": "、".join(notes)})

    # Current-cycle domains with strong reference placement are high-leverage.
    strong = sorted(
        ({"domain": d, "position": p, "your_citations": hit(d)} for d, p in TOP_POSITION.items() if hit(d)),
        key=lambda x: x["position"],
    )

    return {
        "cross_platform_covered": covered,
        "cross_platform_missing": missing,
        "coverage_rate": round(len(covered) / len(CROSS_PLATFORM), 3),
        "ecosystem_gaps": eco_gaps,
        "high_position_hits": strong,
        "category_share": CATEGORY_SHARE,
    }
