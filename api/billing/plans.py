"""CiteAura 套餐能力定义。"""


# Trial access window for new workspaces. Historical migrations retain their original dates.
TRIAL_DAYS = 14


PLANS = {
    "trial": {
        "name": "Trial",
        "monthly_cny": 0,
        "monthly_usd": 0,
        "projects": 3,
        "sample_runs": 3,
    },
    "starter": {
        "name": "Starter",
        "monthly_cny": 599,
        "monthly_usd": 79,
        "projects": 3,
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
}


SUBSCRIBABLE_PLANS = frozenset(("starter", "pro", "agency"))

# 能力按套餐售卖；trial 是完整闭环体验，但受采样次数限制。
PLAN_FEATURES = {
    "scheduled_monitoring": frozenset(("starter", "pro", "agency")),
    "regression_alerts": frozenset(("pro", "agency")),
    "white_label_delivery": frozenset(("agency",)),
}
