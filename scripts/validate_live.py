#!/usr/bin/env python3
"""One bounded real workflow; requires explicit paid-run authorization.

Never called by the offline suite. Credentials come from the existing local
.env/environment. Model and current pricing must be selected by the operator.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import Settings, load_dotenv
from src.llm.provider import OpenAIProvider
from src.orchestration.engine import Orchestrator
from src.storage.database import Store
from src.storage import artifacts

OBJECTIVE = (
    'Use web_search to find the official Python documentation for the built-in '
    'len function, then fetch the official page. Explain what len returns, '
    'cite its exact supporting passage, and use calculate to evaluate 2 + 3 '
    'as a separate arithmetic demonstration. Limit the report to two findings '
    'and two material claims. Distinguish the documented fact from the '
    'calculation. Do not perform any external action beyond read-only research.'
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorize-paid-run', action='store_true',
                        help='Explicitly authorize this single real API-backed attempt')
    parser.add_argument('--model', required=True, help='A model available to your existing API credentials')
    parser.add_argument('--input-usd-per-million', type=float, required=True)
    parser.add_argument('--output-usd-per-million', type=float, required=True)
    parser.add_argument('--search-usd-per-call', type=float, required=True)
    parser.add_argument('--budget', type=float, default=1.0)
    parser.add_argument('--total-budget', type=float, default=2.0,
                        help='Cumulative cap including previous attempts in this projects root')
    args = parser.parse_args(argv)
    if not args.authorize_paid_run:
        parser.error('No paid calls authorized; pass --authorize-paid-run only after approving the stated budget.')
    import math
    for value in (args.input_usd_per_million, args.output_usd_per_million,
                  args.search_usd_per_call, args.budget, args.total_budget):
        if not math.isfinite(value) or value <= 0:
            parser.error('Prices and budgets must be positive finite numbers.')
    load_dotenv()
    if not all(os.environ.get(key) for key in ('OPENAI_API_KEY', 'TAVILY_API_KEY')):
        parser.error('Existing local OPENAI_API_KEY and TAVILY_API_KEY are required; no values are printed.')
    settings = Settings(
        projects_root=os.environ.get('AR_PROJECTS_ROOT', 'projects'),
        budget_usd=args.budget, total_validation_budget_usd=args.total_budget,
        models={role: args.model for role in ('creator', 'evaluator', 'executor', 'auditor')},
        model_prices={args.model: (args.input_usd_per_million, args.output_usd_per_million)},
        tavily_cost_per_search=args.search_usd_per_call,
        max_prompt_revisions=1, max_corrections=1, max_tool_iterations=6,
        max_sources_to_verify=2, max_runtime_s=300, llm_timeout_s=45, max_output_tokens=4000,
    )
    provider = OpenAIProvider(timeout_s=settings.llm_timeout_s,
                              max_output_tokens=settings.max_output_tokens)
    store = Store(os.path.join(settings.projects_root, 'research.db'))
    try:
        engine = Orchestrator(settings, store, client=provider)
        pid = engine.create_project(OBJECTIVE)
        result = engine.run(pid)
        tools = store.list_tool_calls(pid)
        audit = store.load_output(pid, f'audit_{result["corrections"]}') or {}
        checks = {
            'approved': result['state'] == 'COMPLETED',
            'successful_search': any(t['tool'] == 'web_search' and t['ok'] for t in tools),
            'successful_fetch': any(t['tool'] == 'fetch_page' and t['ok'] for t in tools),
            'successful_calculation': any(t['tool'] == 'calculate' and t['ok'] for t in tools),
            'independently_confirmed_source': bool(audit.get('verified_sources')),
            'final_report': artifacts.artifact_exists(settings.projects_root, pid, 'final_report.md'),
        }
        summary = {'validation': 'LIVE_API_BACKED', 'status': result, 'checks': checks,
                   'ledger': engine.ledger.summary(), 'max_output_tokens': settings.max_output_tokens,
                   'configured_prices': settings.model_prices,
                   'search_usd_per_call': settings.tavily_cost_per_search}
        artifacts.write_json(settings.projects_root, pid, 'live_validation.json', summary)
        print(json.dumps(summary, indent=2))
        return 0 if all(checks.values()) else 1
    finally:
        store.close()


if __name__ == '__main__':
    raise SystemExit(main())
