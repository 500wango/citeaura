"""CiteAura 套餐能力定义。"""


PLANS = {
    "trial": {
        "name": "Trial",
        "monthly_cny": 0,
        "monthly_usd": 0,
        "projects": 3,
        "sample_runs": 2,
    },
    "starter": {
        "name": "Starter",
        "monthly_cny": 599,
        "monthly_usd": 79,
        "projects": 3,
        "sample_runs": None,
    },
    "lite": {
        "name": "Lite",
        "monthly_cny": 299,
        "monthly_usd": 39,
        "projects": 1,
        "sample_runs": None,
    },
    "pro": {
        "name": "Pro",
        "monthly_cny": 1499,
        "monthly_usd": 199,
        "projects": 10,
        "sample_runs": None,
    },
    "agency": {
        "name": "Agency",
        "monthly_cny": 3699,
        "monthly_usd": 499,
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


SUBSCRIBABLE_PLANS = frozenset(("lite", "starter", "pro", "agency", "enterprise"))
