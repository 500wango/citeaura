"""试用起步扫描规划：在固定预算内挑选平台组合。"""

from api import config

STARTER_SCAN_BUDGET_USD_CENTS = 200
# 建项时题库尚未生成，用保守题量估算；真实题量在采样前由预算守卫复核。
PLANNING_QUESTION_COUNT = 12
PLANNING_REPEAT = 5


def estimate_plan_cost(platforms, prices, question_count, repeat):
    """返回总调用数与平台成本（分）。"""
    calls_per_platform = max(0, int(question_count)) * max(0, int(repeat))
    total_calls = calls_per_platform * len(platforms)
    amount = sum(calls_per_platform * int(prices.get(code) or 0) for code in platforms)
    return {"calls": total_calls, "cost_cny_fen": amount}


def plan_starter_scan(catalog, question_count=PLANNING_QUESTION_COUNT,
                      repeat=PLANNING_REPEAT, budget_cny_fen=None):
    """贪心装箱：先选一个联网引擎，再补低价引擎；装不下返回 insufficient_budget。"""
    budget = config.trial_starting_budget_cny_fen() if budget_cny_fen is None else int(budget_cny_fen)
    priced = []
    for item in catalog or []:
        code = str(item.get("engine_code") or "").strip()
        price = int(item.get("unit_price_cny_fen") or 0)
        if code and price > 0:
            priced.append({
                "engine_code": code,
                "unit_price_cny_fen": price,
                "search": bool(item.get("search")),
            })
    prices = {item["engine_code"]: item["unit_price_cny_fen"] for item in priced}
    calls_per_platform = max(0, int(question_count)) * max(0, int(repeat))
    per_scan = {code: calls_per_platform * price for code, price in prices.items()}

    ordered = sorted(priced, key=lambda item: (not item["search"], per_scan[item["engine_code"]]))
    chosen = []
    spent = 0
    for item in ordered:
        code = item["engine_code"]
        cost = per_scan[code]
        if cost <= 0 or spent + cost > budget:
            continue
        chosen.append(code)
        spent += cost
        if len(chosen) >= 2 and any(item["search"] for item in ordered if item["engine_code"] in chosen):
            # 已有联网引擎和至少一个补充引擎；继续加只会稀释题量。
            break
    estimate = estimate_plan_cost(chosen, prices, question_count, repeat)
    return {
        "status": "planned" if chosen else "insufficient_budget",
        "platforms": chosen,
        "question_count": max(0, int(question_count)),
        "repeat": max(0, int(repeat)),
        "calls": estimate["calls"],
        "cost_cny_fen": estimate["cost_cny_fen"],
        "budget_cny_fen": budget,
        "budget_usd_cents": STARTER_SCAN_BUDGET_USD_CENTS,
    }


def create_starter_scan_job(budget_cny_fen=None, question_count=PLANNING_QUESTION_COUNT,
                            repeat=PLANNING_REPEAT):
    """为试用工作区生成起步扫描计划；不写数据库，预算与平台价格实时读取。"""
    from api.billing.platform_pool import public_catalog

    return plan_starter_scan(
        public_catalog(),
        question_count=question_count,
        repeat=repeat,
        budget_cny_fen=budget_cny_fen,
    )
