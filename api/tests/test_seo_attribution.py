import json

from api.analytics.router import sanitize_public_properties


def test_public_attribution_properties_strip_full_urls_and_secrets():
    clean = sanitize_public_properties({
        "page_path": "https://citeaura.com/blog/guide?utm_source=secret",
        "first_touch_path": "/blog/guide?token=hidden",
        "referrer_host": "https://www.google.com/search?q=citeaura",
        "source": "google",
        "medium": "organic",
        "campaign": "spring",
        "api_key": "never-store",
        "landing_url": "https://citeaura.com/?token=hidden",
        "organic_search": True,
    })

    assert clean["page_path"] == "/blog/guide"
    assert clean["first_touch_path"] == "/blog/guide"
    assert clean["referrer_host"] == "www.google.com"
    assert clean["organic_search"] is True
    assert "api_key" not in clean
    assert "landing_url" not in clean


def test_utm_labels_keep_summary_values_without_query_strings():
    clean = sanitize_public_properties({
        "source": "https://search.example/path?token=hidden",
        "medium": "organic?secret=hidden",
        "campaign": "spring#fragment",
    })

    assert clean == {
        "campaign": "spring",
        "medium": "organic",
        "source": "search.example",
    }


def test_public_page_view_event_is_whitelisted_and_sanitized():
    from api.analytics.router import ProductEventRequest

    payload = ProductEventRequest(
        name="seo_page_view",
        properties={"page_path": "/for-brands?utm_source=google", "source": "organic"},
    )
    assert payload.name == "seo_page_view"
    assert payload.properties == {"page_path": "/for-brands", "source": "organic"}
