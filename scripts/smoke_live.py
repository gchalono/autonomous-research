#!/usr/bin/env python3
"""Minimal live connectivity smoke tests (Phase B).

Checks, with the smallest practical requests:
  1. OpenAI authentication + configured-model availability + strict
     structured output (one tiny Responses call).
  2. Tavily authentication + search response parsing (one query).
  3. Token usage recording + ledger accounting.

Usage:
    python scripts/smoke_live.py --authorize-paid-run

Output is a JSON summary. Credential VALUES are never printed. Exit code
0 means both providers answered; 2 means credentials missing; 3 means a
provider check failed (see the per-check status). All spend is recorded
in the cumulative validation ledger.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pydantic import BaseModel

from src.config import Settings, load_dotenv
from src.llm.provider import OpenAIProvider
from src.storage.ledger import ValidationLedger


class Ping(BaseModel):
    ok: bool


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorize-paid-run', action='store_true')
    args = parser.parse_args()
    if not args.authorize_paid_run:
        parser.error('Paid smoke checks require --authorize-paid-run; use validate_live.py for a bounded full workflow.')
    load_dotenv()
    settings = Settings.from_env()
    ledger = ValidationLedger(
        os.path.join(settings.projects_root, "validation_ledger.json"),
        settings.total_validation_budget_usd)
    os.makedirs(settings.projects_root, exist_ok=True)
    run_lock = open(os.path.join(settings.projects_root, '.run.lock'), 'a')
    try:
        fcntl.flock(run_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        run_lock.close()
        parser.error('Another research run is active in this projects root.')
    # Process exit closes the lock even after a failed provider check.
    result: dict = {"ledger_before_usd": ledger.total_spent}

    openai_key = bool(os.environ.get("OPENAI_API_KEY"))
    tavily_key = bool(os.environ.get("TAVILY_API_KEY"))
    result["openai_key_present"] = openai_key
    result["tavily_key_present"] = tavily_key
    if not openai_key or not tavily_key:
        result["status"] = "CREDENTIAL_MISSING"
        print(json.dumps(result, indent=2))
        run_lock.close()
        return 2

    overall_ok = True
    if openai_key:
        try:
            provider = OpenAIProvider(fallback_model=settings.model_fallback,
                                      timeout_s=settings.llm_timeout_s, max_output_tokens=256)
            def cost_cb(model, input_tokens, output_tokens, preflight=False):
                cost = settings.estimate_cost_usd(model, input_tokens, output_tokens)
                if preflight:
                    if ledger.total_spent + cost > ledger.cap_usd:
                        from src.orchestration.engine import BudgetExhausted
                        raise BudgetExhausted('Smoke request would exceed cumulative cap')
                else:
                    ledger.record('smoke', 'openai', model, cost, 'smoke_call')
            provider.request_cost_cb = cost_cb
            payload, in_tokens, out_tokens = provider.complete(
                "You are a connectivity probe. Reply with the requested JSON.",
                'Reply with {"ok": true}.', Ping.model_json_schema(),
                settings.models["creator"])
            cost = settings.estimate_cost_usd(
                list(provider.models_used)[0] if provider.models_used else
                settings.models["creator"], in_tokens, out_tokens)
            Ping.model_validate(payload)
            result["openai"] = {
                "status": "CREDENTIAL_VALID", "payload": payload,
                "models_used": sorted(provider.models_used),
                "input_tokens": in_tokens, "output_tokens": out_tokens,
                "estimated_cost_usd": round(cost, 6),
                "response_id": provider.last_response_id,
            }
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            overall_ok = False
            result["openai"] = {"status": "PROVIDER_UNAVAILABLE",
                                "error_class": type(exc).__name__,
                                "error": str(exc)[:300]}
    if tavily_key:
        try:
            charge = settings.tavily_cost_per_search
            if charge <= 0 or ledger.total_spent + charge > ledger.cap_usd:
                raise ValueError('Set a positive AR_TAVILY_COST_PER_SEARCH within the remaining cumulative cap')
            from src.tools.search import _search_tavily
            from src.tools.base import ToolResult
            try:
                rows = _search_tavily('autonomous research', 2)
            finally:
                ledger.record('smoke', 'tavily', 'web_search', charge, 'smoke_search')
            res = ToolResult(ok=bool(rows), provenance={'result_urls': [row['url'] for row in rows]})
            result["tavily"] = {
                "status": "CREDENTIAL_VALID" if res.ok else "PROVIDER_UNAVAILABLE",
                "ok": res.ok,
                "result_urls": (res.provenance or {}).get("result_urls", []),
                "error": res.error,
            }
            if not res.ok:
                overall_ok = False
        except Exception as exc:  # noqa: BLE001
            overall_ok = False
            result["tavily"] = {"status": "PROVIDER_UNAVAILABLE",
                                "error_class": type(exc).__name__,
                                "error": str(exc)[:300]}
    result["ledger_after_usd"] = ledger.total_spent
    result["status"] = "OK" if overall_ok else "FAILED"
    print(json.dumps(result, indent=2))
    run_lock.close()
    return 0 if overall_ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
