"""试用起步扫描预算规划测试。"""

from api.billing.starter_scan import estimate_plan_cost, plan_starter_scan


CATALOG = [
    {"engine_code": "searchy", "unit_price_cny_fen": 10, "search": True},
    {"engine_code": "cheap", "unit_price_cny_fen": 5, "search": False},
    {"engine_code": "pricey", "unit_price_cny_fen": 40, "search": True},
]


def test_estimate_plan_cost_multiplies_questions_and_rounds():
    estimate = estimate_plan_cost(["cheap"], {"cheap": 5}, question_count=3, repeat=5)
    assert estimate == {"calls": 15, "cost_cny_fen": 75}


def test_planner_prefers_one_search_engine_then_cheapest():
    plan = plan_starter_scan(CATALOG, question_count=2, repeat=5, budget_cny_fen=150)
    assert plan["status"] == "planned"
    assert plan["platforms"] == ["searchy", "cheap"]
    assert plan["calls"] == 20
    assert plan["cost_cny_fen"] == 150


def test_planner_stays_within_budget():
    plan = plan_starter_scan(CATALOG, question_count=2, repeat=5, budget_cny_fen=120)
    assert plan["platforms"] == ["searchy"]
    assert plan["cost_cny_fen"] == 100


def test_planner_reports_insufficient_budget():
    plan = plan_starter_scan(CATALOG, question_count=2, repeat=5, budget_cny_fen=10)
    assert plan["status"] == "insufficient_budget"
    assert plan["platforms"] == []
    assert plan["calls"] == 0


def test_planner_ignores_unpriced_or_unknown_entries():
    plan = plan_starter_scan(
        [
            {"engine_code": "", "unit_price_cny_fen": 10, "search": True},
            {"engine_code": "free", "unit_price_cny_fen": 0, "search": True},
            {"engine_code": "cheap", "unit_price_cny_fen": 5, "search": False},
        ],
        question_count=1, repeat=1, budget_cny_fen=10,
    )
    assert plan["platforms"] == ["cheap"]
    assert plan["cost_cny_fen"] == 5
