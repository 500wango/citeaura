from api.adapters import competitor_scope


def test_legacy_model_platforms_are_quarantined_for_non_model_products():
    config = competitor_scope.normalize_config({
        "brand": {
            "name": "CiteAura",
            "industry": "Generative Engine Optimization software",
            "definition": "CiteAura measures brand mentions and citations in AI answers.",
            "products": ["AI visibility monitoring"],
        },
        "competitors": [
            {"name": "ChatGPT", "confirmed": True},
            {"name": "Claude", "confirmed": True},
            {
                "name": "Peec AI",
                "domain": "https://peec.ai",
                "confirmed": False,
                "relationship": "direct_competitor",
                "relationship_source": "ai_site_profile",
                "relationship_confidence": "high",
                "category_overlap": "AI visibility measurement software",
                "buyer_overlap": "Brand and marketing teams",
                "job_overlap": "Measure visibility in AI answers",
            },
        ],
    })

    assert [item["name"] for item in config["competitors"]] == ["Peec AI"]
    assert config["competitors"][0]["relationship"] == "direct_competitor"
    assert {item["name"] for item in config["competitor_review"]} == {"ChatGPT", "Claude"}
    assert all(item["benchmark_eligible"] is False for item in config["competitor_review"])


def test_unclassified_legacy_candidates_are_quarantined_instead_of_assumed_direct():
    config = competitor_scope.normalize_config({
        "brand": {"name": "Example", "industry": "Industrial operations software"},
        "competitors": [
            {"name": "Generic workflow suite", "confirmed": True},
            {"name": "Cloud infrastructure vendor", "domain": "https://cloud.example"},
        ],
    })

    assert config["competitors"] == []
    assert {item["relationship"] for item in config["competitor_review"]} == {"unknown"}
    assert all(
        item["exclusion_reason"] == "direct_relationship_not_established"
        for item in config["competitor_review"]
    )


def test_explicit_user_classification_can_override_platform_guard():
    brand = {"name": "AnswerCo", "industry": "Customer support software"}
    active, review = competitor_scope.normalize_competitors([{
        "name": "ChatGPT",
        "relationship": "direct_competitor",
        "relationship_source": "user",
        "relationship_review_required": False,
    }], brand)

    assert [item["name"] for item in active] == ["ChatGPT"]
    assert review == []


def test_stronger_duplicate_classification_wins_without_reordering():
    active, review = competitor_scope.normalize_competitors([
        {"name": "Rival One"},
        {"name": "Rival Two", "relationship": "unknown"},
        {
            "name": "Rival One",
            "relationship": "direct_competitor",
            "relationship_source": "user",
        },
    ], {"name": "Example"})

    assert [item["name"] for item in active] == ["Rival One"]
    assert [item["name"] for item in review] == ["Rival Two"]


def test_discovery_requires_direct_overlap_and_official_url():
    prompts = []

    def ask_json(prompt):
        prompts.append(prompt)
        return {"competitors": [
            {
                "name": "Profound",
                "official_url": "https://tryprofound.com",
                "relationship": "direct_competitor",
                "category_overlap": "AI visibility measurement",
                "buyer_overlap": "Brand and marketing teams",
                "job_overlap": "Measure brand visibility in AI answers",
                "confidence": "high",
            },
            {
                "name": "ChatGPT",
                "official_url": "https://chatgpt.com",
                "relationship": "ecosystem_platform",
                "category_overlap": "",
                "buyer_overlap": "",
                "job_overlap": "",
                "confidence": "high",
            },
            {
                "name": "Imaginary Rival",
                "relationship": "direct_competitor",
                "category_overlap": "AI visibility measurement",
                "buyer_overlap": "Brand teams",
                "job_overlap": "Track citations",
                "confidence": "low",
            },
        ]}

    result = competitor_scope.discover_competitors(ask_json, {
        "name": "CiteAura",
        "site": "https://citeaura.com",
        "industry": "Generative Engine Optimization software",
        "definition": "CiteAura measures brand visibility in AI answers.",
        "products": ["Citation monitoring", "AI visibility reports"],
        "target_users": "Brands and agencies",
    })

    assert [item["name"] for item in result] == ["Profound"]
    assert result[0]["relationship_source"] == "ai_site_profile"
    assert result[0]["relationship_review_required"] is True
    assert "same purchasing decision" in prompts[0]


def test_model_provider_projects_can_retain_model_provider_peers():
    active, review = competitor_scope.normalize_competitors(
        [{
            "name": "OpenAI",
            "official_url": "https://openai.com",
            "confirmed": False,
            "relationship": "direct_competitor",
            "confidence": "medium",
            "category_overlap": "Foundation model provider",
            "buyer_overlap": "Developers and enterprises buying model access",
            "job_overlap": "Purchase API access to hosted language models",
        }],
        {
            "name": "ModelCo",
            "industry": "Foundation model provider",
            "definition": "ModelCo develops large language models for developers.",
        },
    )

    assert [item["name"] for item in active] == ["OpenAI"]
    assert review == []


def test_visibility_products_are_not_mistaken_for_answer_engine_providers():
    active, review = competitor_scope.normalize_competitors(
        [{"name": "ChatGPT", "domain": "https://chatgpt.com", "confirmed": True}],
        {
            "name": "VisibilityCo",
            "industry": "AI search engine visibility software",
            "definition": "VisibilityCo monitors how brands appear in AI assistant and search engine answers.",
        },
    )

    assert active == []
    assert review[0]["relationship"] == "ecosystem_platform"


def test_brand_aliases_and_same_site_products_cannot_compete_with_themselves():
    active, review = competitor_scope.normalize_competitors([
        {
            "name": "Example Cloud",
            "official_url": "https://example.com/cloud",
            "relationship": "direct_competitor",
            "relationship_source": "user",
        },
        {
            "name": "Example Incorporated",
            "official_url": "https://other.example",
            "relationship": "direct_competitor",
            "relationship_source": "user",
        },
    ], {
        "name": "Example",
        "aliases": ["Example Incorporated"],
        "site": "https://example.com",
    })

    assert active == []
    assert review == []
