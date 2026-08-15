import json
import re

import pytest

from api.adapters import audit_presentation


ALL_ENGINE_CODES = [
    "NO_CANONICAL", "SPA_SHELL", "SHORT_CONTENT", "BAD_H1", "FEW_H2",
    "LOW_LIST_DENSITY", "NO_DEFINITION", "NO_NUMBERS", "NO_COMPARISON",
    "NO_HOWTO", "NO_FAQ", "NO_DATE", "FEW_EXTERNAL_LINKS", "NO_JSONLD",
    "LOW_RELEVANCE",
]
HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def _raw_page(url, *, word_count=40, codes=None, blocks=None, score=12):
    return {
        "url": url,
        "title": "Source page",
        "word_count": word_count,
        "score": score,
        "grade": "D",
        "dimensions": {"\u53ef\u6293\u53d6\u6027": 10, "\u5185\u5bb9\u957f\u5ea6": 0},
        "blocks": blocks or {
            "\u5b9a\u4e49": False,
            "\u6570\u5b57\u4e8b\u5b9e": False,
            "\u5bf9\u6bd4": False,
            "\u64cd\u4f5c\u6b65\u9aa4": False,
            "FAQ": False,
        },
        "jsonld_types": [],
        "issues": ["P1 \u6240\u6709\u9875\u9762\u90fd\u663e\u793a\u7684\u4e2d\u6587\u6a21\u677f\u7ed3\u8bba"],
        "issue_codes": list(codes or []),
    }


def _evidence(url, *, title="Page", h1=None, h2=None, word_count=180,
              para_count=6, schema=None, status=200, canonical=True,
              external_links=1, text="Useful public content"):
    return {
        "url": url,
        "status": status,
        "title": title,
        "meta_description": "",
        "meta_robots": "",
        "canonical": url if canonical else "",
        "h1": [title] if h1 is None else h1,
        "h2": ["Overview", "Details", "Evidence"] if h2 is None else h2,
        "word_count": word_count,
        "para_count": para_count,
        "external_links": external_links,
        "jsonld_types": list(schema or []),
        "text": text,
    }


def _audit(pages):
    return {
        "slug": "example",
        "audited_at": "2026-08-14T10:00:00+00:00",
        "market": "global",
        "site": {
            "root": "https://example.com", "pages_crawled": len(pages),
            "pages_ok": len(pages), "has_sitemap": True, "has_llms_txt": True,
            "ai_bots_blocked": [],
        },
        "language_coverage": {"distribution": {"en": len(pages)}, "en_pages": len(pages)},
        "page_count": len(pages),
        "avg_score": 12,
        "grade_distribution": {"A": 0, "B": 0, "C": 0, "D": len(pages)},
        "site_issues": ["\u4e2d\u6587\u5f15\u64ce\u7ed3\u8bba"],
        "pages": pages,
    }


@pytest.mark.parametrize(("page", "expected"), [
    ({"url": "https://saas.example/platform", "jsonld_types": ["SoftwareApplication"]}, "product_service"),
    ({"url": "https://maker.example/products/industrial-pump", "jsonld_types": ["Product"]}, "product_service"),
    ({"url": "https://agency.example/services/brand-strategy", "jsonld_types": ["Service"]}, "product_service"),
    ({"url": "https://shop.example/collections/pumps", "jsonld_types": ["CollectionPage", "ItemList"]}, "category_listing"),
    ({"url": "https://shop.example/products"}, "category_listing"),
    ({"url": "https://shop.example/pricing", "jsonld_types": ["SoftwareApplication"]}, "pricing"),
    ({"url": "https://example.com/blog/widget-vs-rival"}, "comparison"),
    ({"url": "https://example.com/docs/api-reference"}, "docs_howto"),
    ({"url": "https://example.com/en/contact"}, "contact"),
    ({"url": "https://example.com/privacy-policy"}, "legal"),
    ({"url": "https://example.com/login"}, "auth_utility"),
])
def test_classify_page_uses_page_function_not_industry(page, expected):
    assert audit_presentation.classify_page(page)["id"] == expected


def test_contact_page_suppresses_unrelated_long_form_and_block_findings():
    url = "https://manufacturer.example/en/contact"
    raw = _raw_page(url, codes=ALL_ENGINE_CODES)
    evidence = _evidence(
        url, title="Contact LANCCO", h2=[], word_count=44, para_count=3,
        schema=[], external_links=0,
    )

    result = audit_presentation.present_audit_data(_audit([raw]), [evidence])
    page = result["pages"][0]

    assert page["role"]["id"] == "contact"
    assert page["applicable_score"] is None
    assert page["evaluation_status"] == "insufficient_evidence"
    assert page["findings"] == []
    assert page["issues"] == []
    assert set(item["id"] for item in page["checks"] if item["status"] == "passed") == {
        "accessibility", "indexability", "canonical", "rendered_content", "h1",
    }
    assert not HAN.search(json.dumps({
        "role": page["role"], "issues": page["issues"],
        "findings": page["findings"], "site_findings": result["site_findings"],
    }, ensure_ascii=False))


@pytest.mark.parametrize(("url", "title", "schema", "expected", "suppressed"), [
    ("https://shop.example/pricing", "Pricing", ["Product"], {"NO_NUMBERS"}, {"NO_FAQ", "NO_COMPARISON", "NO_HOWTO"}),
    ("https://example.com/compare/a-vs-b", "A vs B", [], {"NO_NUMBERS", "NO_COMPARISON"}, {"NO_FAQ", "NO_HOWTO"}),
    ("https://example.com/privacy", "Privacy Policy", [], {"NO_DATE"}, {"NO_FAQ", "NO_COMPARISON", "NO_HOWTO"}),
    ("https://publisher.example/news/update", "Product update", ["NewsArticle"], {"NO_DATE", "FEW_EXTERNAL_LINKS"}, {"NO_FAQ", "NO_COMPARISON"}),
])
def test_role_specific_checks_only_report_applicable_gaps(url, title, schema, expected, suppressed):
    raw = _raw_page(url, word_count=500, codes=[
        "NO_NUMBERS", "NO_COMPARISON", "NO_HOWTO", "NO_FAQ", "NO_DATE", "FEW_EXTERNAL_LINKS",
    ])
    evidence = _evidence(
        url, title=title, word_count=500, para_count=15, schema=schema,
        external_links=0, text="Detailed content",
    )
    page = audit_presentation.present_audit_data(_audit([raw]), [evidence])["pages"][0]
    codes = {item["code"] for item in page["findings"]}

    assert expected <= codes
    assert not (suppressed & codes)


def test_howto_requirement_depends_on_procedural_page_evidence():
    api_url = "https://example.com/docs/api-reference"
    guide_url = "https://example.com/docs/getting-started-guide"
    pages = [
        _raw_page(api_url, word_count=400, codes=["NO_HOWTO"]),
        _raw_page(guide_url, word_count=400, codes=["NO_HOWTO"]),
    ]
    evidence = [
        _evidence(api_url, title="API Reference", word_count=400, para_count=12),
        _evidence(guide_url, title="Getting Started Guide", word_count=400, para_count=12),
    ]
    result = audit_presentation.present_audit_data(_audit(pages), evidence)
    by_url = {page["url"]: {item["code"] for item in page["findings"]} for page in result["pages"]}

    assert "NO_HOWTO" not in by_url[api_url]
    assert "NO_HOWTO" in by_url[guide_url]


def test_unreachable_page_suppresses_cascading_content_findings():
    url = "https://example.com/article/unavailable"
    raw = _raw_page(url, codes=["PAGE_UNREACHABLE", *ALL_ENGINE_CODES])
    evidence = _evidence(url, title="Unavailable", status=503, word_count=0, para_count=0, h1=[], h2=[])

    page = audit_presentation.present_audit_data(_audit([raw]), [evidence])["pages"][0]

    assert [item["code"] for item in page["findings"]] == ["PAGE_UNREACHABLE"]
    assert page["applicable_score"] is None
    assert page["evaluation_status"] == "insufficient_evidence"
    assert page["check_summary"]["not_evaluated"] == len(audit_presentation.CHECK_WEIGHTS) - 1


def test_aggregate_score_excludes_utility_pages_and_recomputes_role_specific_blocks():
    home = _raw_page("https://example.com", word_count=300, codes=["NO_DEFINITION"])
    pricing = _raw_page("https://example.com/pricing", word_count=200, codes=["NO_NUMBERS", "NO_FAQ"])
    utility = _raw_page("https://example.com/checkout", codes=ALL_ENGINE_CODES)
    evidence = [
        _evidence("https://example.com", title="Example", word_count=300, para_count=10, schema=["Organization"]),
        _evidence("https://example.com/pricing", title="Pricing", word_count=200, para_count=8, schema=["Product"]),
        _evidence("https://example.com/checkout", title="Checkout", word_count=2, para_count=0, h1=[], h2=[]),
    ]
    original = _audit([home, pricing, utility])
    before = json.dumps(original, ensure_ascii=False, sort_keys=True)

    result = audit_presentation.present_audit_data(original, evidence)

    assert result["check_summary"]["excluded_pages"] == 1
    assert result["applicable_avg_score"] is not None
    assert {item["block"]: (item["missing_pages"], item["total"]) for item in result["block_gap"]} == {
        "definition": (1, 1),
        "numeric_facts": (1, 1),
    }
    assert json.dumps(original, ensure_ascii=False, sort_keys=True) == before


def test_unknown_engine_code_has_stable_english_fallback():
    url = "https://example.com/about"
    raw = _raw_page(url, word_count=200, codes=["NEW_ENGINE_CHECK"])
    evidence = _evidence(url, title="About us", word_count=200, para_count=8, schema=["AboutPage"])

    page = audit_presentation.present_audit_data(_audit([raw]), [evidence])["pages"][0]
    finding = next(item for item in page["findings"] if item["code"] == "NEW_ENGINE_CHECK")

    assert finding["title"] == "New Engine Check"
    assert not HAN.search(json.dumps(finding, ensure_ascii=False))


def test_non_ascii_unknown_code_and_dimension_get_ascii_fallbacks():
    url = "https://example.com/about"
    raw = _raw_page(url, word_count=200, codes=["\u65b0\u68c0\u67e5"])
    raw["dimensions"] = {"\u672a\u77e5\u7ef4\u5ea6": 4}
    evidence = _evidence(url, title="About us", word_count=200, para_count=8, schema=["AboutPage"])

    page = audit_presentation.present_audit_data(_audit([raw]), [evidence])["pages"][0]

    assert page["issue_codes"] == ["UNCLASSIFIED_ENGINE_CHECK"]
    assert page["engine_dimensions"] == {"dimension_1": 4}
    assert not HAN.search(json.dumps(page["findings"], ensure_ascii=False))
