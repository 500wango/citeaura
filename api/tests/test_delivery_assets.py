from api.adapters.delivery_assets import classify_pack_readiness


def test_asset_readiness_distinguishes_diagnostic_and_implementation_gates():
    result = classify_pack_readiness(
        {"page_count": 1, "score_status": "reported"},
        {"ready": 2, "needs_review": 0, "template": 0},
        {"confidence": {"sufficient": True}},
        {"available": False, "approved": False},
    )

    assert result["pack_kind"] == "implementation"
    assert result["diagnostic_ready"] is True
    assert result["visibility_ready"] is True
    assert result["implementation_ready"] is True


def test_asset_readiness_keeps_unmeasured_visibility_in_implementation_backlog():
    result = classify_pack_readiness(
        {"page_count": 1, "score_status": "reported"},
        {"ready": 1, "needs_review": 0, "template": 0},
        {"confidence": {"sufficient": False, "label": "Not measured"}},
        {"available": False, "approved": False},
    )

    assert result["pack_kind"] == "diagnostic"
    assert result["diagnostic_ready"] is True
    assert result["implementation_ready"] is False
    assert any("AI visibility is not measured" in item for item in result["implementation_backlog"])


def test_asset_readiness_blocks_empty_audits():
    result = classify_pack_readiness(
        {"page_count": 0},
        {"ready": 0, "needs_review": 0, "template": 0},
        {"confidence": {"sufficient": False}},
        {"available": False, "approved": False},
    )

    assert result["pack_kind"] == "review"
    assert result["diagnostic_ready"] is False
    assert result["readiness"] == "review_required"
