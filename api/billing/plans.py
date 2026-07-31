"""DisvorAI 套餐能力定义。"""


PLANS = {
    "trial": {
        "name": "Trial",
        "monthly_cny": 0,
        "monthly_usd": 0,
        "projects": 3,
        "sample_runs": 2,
    },
    "pro": {
        "name": "Pro",
        "monthly_cny": 199,
        "monthly_usd": 29,
        "projects": 10,
        "sample_runs": None,
    },
    "agency": {
        "name": "Agency",
        "monthly_cny": 599,
        "monthly_usd": 79,
        "projects": 30,
        "sample_runs": None,
    },
    "enterprise": {
        "name": "Enterprise",
        "monthly_cny": None,
        "monthly_usd": None,
        "projects": None,
        "sample_runs": None,
    },
}


SUBSCRIBABLE_PLANS = frozenset(("pro", "agency", "enterprise"))
