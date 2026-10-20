"""校验官网公开声明与 features.yaml / engine_capabilities.json 一致。"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api.adapters import capabilities  # noqa: E402

PUBLIC_PAGES = ("web/index.html", "web/pricing.html")
FORBIDDEN_CLAIMS = (
    "Enterprise",
    "OIDC SSO",
    "Enterprise SSO",
    "audit event logs",
    "Dedicated private deploy",
    "custom SLA",
    "SOC 2 certified",
)
TRIAL_CLAIM = re.compile(r"\b7-day\b|\b7 天\b|\b7天\b", re.IGNORECASE)


def _attr(html, name):
    match = re.search(rf'data-{re.escape(name)}="([^"]*)"', html)
    return match.group(1) if match else None


def check_page(path, api_count, surface_count, trial_days):
    problems = []
    html = (ROOT / path).read_text("utf-8")
    for claim in FORBIDDEN_CLAIMS:
        if claim.lower() in html.lower():
            problems.append(f"{path}: forbidden public claim {claim!r}")
    if TRIAL_CLAIM.search(html):
        problems.append(f"{path}: stale 7-day trial claim")
    declared_api = _attr(html, "engine-count")
    declared_surface = _attr(html, "product-surface-count")
    declared_trial = _attr(html, "trial-days")
    if declared_api is not None and int(declared_api) != api_count:
        problems.append(f"{path}: data-engine-count={declared_api}, catalog={api_count}")
    if declared_surface is not None and int(declared_surface) != surface_count:
        problems.append(f"{path}: data-product-surface-count={declared_surface}, catalog={surface_count}")
    if declared_trial is not None and int(declared_trial) != trial_days:
        problems.append(f"{path}: data-trial-days={declared_trial}, catalog={trial_days}")
    for feature_id in re.findall(r'data-feature="([^"]+)"', html):
        item = capabilities.feature(feature_id)
        if item is None:
            problems.append(f"{path}: unknown data-feature={feature_id!r}")
        elif not item.get("public") or item.get("status") in ("planned", "removed", "internal"):
            problems.append(f"{path}: non-public feature {feature_id!r} advertised")
    return problems


def check_plans():
    problems = []
    html = (ROOT / "web/pricing.html").read_text("utf-8")
    plans = capabilities.public_plans()
    for name in plans:
        if not re.search(rf"\b{re.escape(name)}\b", html, re.IGNORECASE):
            problems.append(f"web/pricing.html: public plan {name!r} missing")
    if re.search(r"\benterprise\b", html, re.IGNORECASE):
        problems.append("web/pricing.html: enterprise plan still advertised")
    return problems


def main():
    catalog = capabilities.load_capabilities()
    features = capabilities.load_features()
    api_count = len(capabilities.api_providers())
    surface_count = len(capabilities.manual_surfaces())
    trial_days = int(features.get("trial_days") or 0)
    problems = check_plans()
    for path in PUBLIC_PAGES:
        problems.extend(check_page(path, api_count, surface_count, trial_days))
    if api_count + surface_count <= 0:
        problems.append("catalog is empty")
    for problem in problems:
        print(f"[claims] {problem}")
    if problems:
        return 1
    print(f"[claims] OK: {api_count} API engines, {surface_count} product surfaces, {trial_days}-day trial")
    return 0


if __name__ == "__main__":
    sys.exit(main())
