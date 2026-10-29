"""Explicit migration of historical synthetic test policies, never production.

VERIFIED_OFFICIAL is a simulated review declaration in these isolated fixtures.
It does not certify prices or enable a production policy or allowance.
"""
import copy


def reviewed_fixture(data):
    p = copy.deepcopy(data)
    p.update(policy_schema_version=1, state='reviewed', experiment_id='bounded-live-experiment-1',
             monetary_precision=6, budget_micro_usd=1000000,
             max_individual_reservation_micro_usd=1000000,
             max_aggregate_reserved_micro_usd=1000000,
             max_concurrent_requests=1, max_sdk_retries=0,
             pricing_references={'openai':['https://openai.com/api/pricing/'],
                                 'tavily':['https://docs.tavily.com/documentation/api-credits']})
    p.setdefault('openai', {})
    p.setdefault('tavily', None)
    for model in p['openai'].values():
        model.setdefault('input_token_overhead', 256)
        model.setdefault('input_bound_mode', 'utf8_text')
        model['pricing_status'] = 'VERIFIED_OFFICIAL'
        for field in ('input_usd_per_million', 'output_usd_per_million'):
            if field in model and type(model[field]) is float: model[field] = str(model[field])
    if p['tavily'] is not None:
        p['tavily']['pricing_status'] = 'VERIFIED_OFFICIAL'
        p['tavily']['max_credits_per_search'] = 1
        for field in ('basic_search_max_usd', 'usd_per_credit'):
            if field in p['tavily'] and type(p['tavily'][field]) is float: p['tavily'][field] = str(p['tavily'][field])
    return p
