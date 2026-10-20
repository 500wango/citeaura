"""引擎能力金丝雀：有 Key 时验证联网检索证据，无 Key 时只做结构校验。"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "engine" / "scripts"))

from api.adapters import capabilities  # noqa: E402
import sample  # noqa: E402

PROBE_QUESTION = "What changed in AI search this week? Cite at least one source."


def structural_problems():
    import geo

    from capabilities import validate_registries

    return validate_registries(sample.PROVIDERS, geo.DEFAULT_PLATFORMS)


def probe(provider, timeout):
    key_env = provider.get("key_env")
    if not key_env or not os.environ.get(key_env):
        return {"status": "skipped", "reason": f"{key_env} not set"}
    try:
        result = sample.ask(provider["code"], PROBE_QUESTION, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - 探针失败只记录，不修改清单
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"[:500]}
    if not result.get("ok"):
        return {"status": "error", "reason": str(result.get("error") or "unknown")[:500]}
    citations = result.get("citations") or []
    searched = bool(result.get("searched"))
    if provider["sampling_mode"] == "api_search" and not (searched and citations):
        return {
            "status": "failed",
            "reason": "declared api_search but probe returned no search/citation evidence",
            "searched": searched,
            "citations": len(citations),
        }
    return {"status": "passed", "searched": searched, "citations": len(citations)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Canary-check declared engine capabilities")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--write", action="store_true", help="Persist canary results into engine_capabilities.json")
    parser.add_argument("--offline", action="store_true", help="Only validate structure")
    args = parser.parse_args(argv)

    problems = structural_problems()
    results = {}
    if not args.offline:
        for provider in capabilities.all_surfaces():
            if provider["sampling_mode"] == "manual_product":
                results[provider["code"]] = {"status": "manual", "reason": "product surface"}
                continue
            results[provider["code"]] = probe(provider, args.timeout)
    else:
        for provider in capabilities.all_surfaces():
            results[provider["code"]] = {"status": "structural"}

    if args.write:
        catalog = capabilities.load_capabilities()
        checked_at = datetime.now(timezone.utc).isoformat()
        for group in ("api_providers", "manual_surfaces"):
            for item in catalog[group]:
                outcome = results.get(item["code"]) or {}
                item["canary"] = {
                    "status": outcome.get("status", "unverified"),
                    "checked_at": checked_at,
                    "evidence": outcome,
                }
        capabilities.CAPABILITIES_PATH.write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", "utf-8",
        )
        capabilities.load_capabilities.cache_clear()
        capabilities.load_features.cache_clear()

    report = {"structural_problems": problems, "results": results}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    failed = [code for code, outcome in results.items() if outcome.get("status") in ("failed", "error")]
    return 1 if problems or failed else 0


if __name__ == "__main__":
    sys.exit(main())
