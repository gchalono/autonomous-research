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
from src.tools.retrieval import fetch_url

SOURCE_URL = 'https://raw.githubusercontent.com/python/cpython/3.12/Doc/library/constants.rst'

OBJECTIVE = (
    'Use web_search to locate the official CPython 3.12 built-in constants '
    'documentation, then fetch its short upstream source at ' + SOURCE_URL + '. '
    'Explain that None is the sole instance of NoneType, citing the exact '
    'supporting passage as a VERIFIED claim. Use calculate to evaluate 2 + 3 '
    'as a separate arithmetic demonstration. Record that claim as ESTIMATED, '
    'with text "2 + 3 = 5", no source_ids, and the exact expression in '
    'calculation_expressions. Limit the report to two findings '
    'and two material claims. Distinguish the documented fact from the '
    'calculation. Do not perform any external action beyond read-only research.'
)


def acceptance_checks(result, tools, audit, report, final_report):
    """Bind successful actions and independently checked evidence to this objective."""
    linked = {cid for finding in report.get('findings', []) for cid in finding.get('claim_ids', [])}
    sources = {s['id']: s for s in report.get('sources', [])
               if s.get('url') == SOURCE_URL and s['id'] in audit.get('verified_sources', [])
               and 'sole instance' in s.get('passage', '') and 'NoneType' in s.get('passage', '')}
    claims = [c for c in report.get('claims', []) if c.get('id') in linked]
    computed = {json.loads(t['arguments_json']).get('expression') for t in tools
                if t['tool'] == 'calculate' and t['ok']
                and json.loads(t['arguments_json']).get('expression', '').replace(' ', '') == '2+3'
                and t.get('output_preview', '').split(' = ')[-1] == '5'}
    return {
        'approved': result['state'] == 'COMPLETED' and audit.get('decision') == 'APPROVE',
        'successful_search': any(t['tool'] == 'web_search' and t['ok'] for t in tools),
        'successful_fetch': any(t['tool'] == 'fetch_page' and t['ok']
                                and json.loads(t['arguments_json']).get('url') == SOURCE_URL for t in tools),
        'documented_fact': any(c.get('classification') == 'VERIFIED'
                               and 'None' in c.get('text', '') and 'NoneType' in c.get('text', '')
                               and bool(set(c.get('source_ids', [])) & sources.keys()) for c in claims),
        'successful_calculation': bool(computed),
        'reported_calculation': any(c.get('classification') == 'ESTIMATED'
                                    and '2+3=5' in c.get('text', '').replace(' ', '')
                                    and bool(set(c.get('calculation_expressions', [])) & computed) for c in claims),
        'final_report': final_report,
    }


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
    try:
        _, source_text = fetch_url(SOURCE_URL)
        if 'sole instance' not in source_text or 'NoneType' not in source_text:
            raise ValueError('Expected reference text unavailable')
    except Exception as exc:
        parser.error(f'Free source preflight failed ({type(exc).__name__}); fix DNS/proxy/source access before paid calls.')
    settings = Settings(
        projects_root=os.environ.get('AR_PROJECTS_ROOT', 'projects'),
        budget_usd=args.budget, total_validation_budget_usd=args.total_budget,
        models={role: args.model for role in ('creator', 'evaluator', 'executor', 'auditor')},
        model_prices={args.model: (args.input_usd_per_million, args.output_usd_per_million)},
        tavily_cost_per_search=args.search_usd_per_call,
        max_prompt_revisions=1, max_corrections=1, max_tool_iterations=6,
        max_tool_calls=6, max_model_requests=20,
        max_sources_to_verify=2, max_runtime_s=300, llm_timeout_s=45, max_output_tokens=4000,
    )
    provider = OpenAIProvider(timeout_s=settings.llm_timeout_s,
                              max_output_tokens=settings.max_output_tokens)
    store = Store(os.path.join(settings.projects_root, 'research.db'))
    try:
        engine = Orchestrator(settings, store, client=provider)
        pid = engine.create_project(OBJECTIVE)
        diagnostic = None
        try:
            result = engine.run(pid)
        except Exception as exc:
            # Keep partial project/accounting evidence and never automatically
            # retry. Do not echo exception bodies that may contain credentials.
            result = engine.status(pid)
            diagnostic = {'error_class': type(exc).__name__,
                          'action': 'Inspect retained project history and accounting before any authorized retry.'}
        tools = store.list_tool_calls(pid)
        audit = store.load_output(pid, f'audit_{result["corrections"]}') or {}
        report = store.load_output(pid, f'execution_{result["corrections"]}') or {}
        checks = acceptance_checks(result, tools, audit, report,
                                   artifacts.artifact_exists(settings.projects_root, pid, 'final_report.md'))
        usage = [e for e in engine.ledger.entries if e['project_id'] == pid and e['kind'] == 'llm_call']
        checks['observed_usage_recorded'] = bool(usage) and all(e.get('observed_usage') is not None for e in usage)
        checks['no_unhandled_error'] = diagnostic is None
        summary = {'validation': 'LIVE_API_BACKED', 'status': result, 'checks': checks,
                   'ledger': engine.ledger.summary(), 'max_output_tokens': settings.max_output_tokens,
                   'configured_prices': settings.model_prices,
                   'search_usd_per_call': settings.tavily_cost_per_search,
                   'limits': {'model_requests': settings.max_model_requests,
                              'tool_calls': settings.max_tool_calls},
                   'diagnostic': diagnostic}
        artifacts.write_json(settings.projects_root, pid, 'live_validation.json', summary)
        print(json.dumps(summary, indent=2))
        return 0 if all(checks.values()) else 1
    finally:
        store.close()


if __name__ == '__main__':
    raise SystemExit(main())
