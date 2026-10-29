"""Strict, offline policy contract. Review declarations are not billing proof.

Schema validation never provisions a ledger or performs network I/O. A draft
can be inspected structurally but cannot be used for paid authorization.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from urllib.parse import urlsplit

POLICY_SCHEMA_VERSION = 1
SYSTEM_CAP_MICRO_USD = 1_000_000
EXPERIMENT = 'bounded-live-experiment-1'
ROOT_FIELDS = {
    'policy_schema_version', 'state', 'experiment_id', 'currency', 'monetary_precision',
    'budget_micro_usd', 'max_individual_reservation_micro_usd',
    'max_aggregate_reserved_micro_usd', 'max_concurrent_requests', 'max_sdk_retries',
    'evidence', 'expires_at', 'pricing_references', 'openai', 'tavily',
}
MODEL_FIELDS = {
    'max_input_tokens', 'max_output_tokens', 'max_request_bytes', 'input_token_overhead',
    'input_bound_mode', 'input_usd_per_million', 'output_usd_per_million', 'pricing_status',
}
CONTEXT_FIELDS = {'provider_context_tokens', 'context_evidence'}
SEARCH_FIELDS = {'basic_search_max_usd', 'usd_per_credit', 'max_credits_per_search', 'pricing_status'}
STATUSES = {'VERIFIED_OFFICIAL', 'VERIFIED_ACCOUNT_SPECIFIC', 'PARTIALLY_VERIFIED', 'UNVERIFIED', 'CONTRADICTED'}
VERIFIED = {'VERIFIED_OFFICIAL', 'VERIFIED_ACCOUNT_SPECIFIC'}


class PolicyError(ValueError):
    pass


def _fields(value, required, optional=frozenset()):
    if type(value) is not dict or not required <= value.keys() or value.keys() - required - optional:
        raise PolicyError('missing or unknown policy fields')


def _integer(value, minimum=1, maximum=None, nullable=False):
    if nullable and value is None:
        return
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise PolicyError('invalid integer constraint')


def _money(value, nullable=False):
    if nullable and value is None:
        return None
    # JSON float literals are deliberately disallowed. Prices are exact decimal
    # strings or integers, never silently rounded binary floating-point values.
    if type(value) not in (str, int):
        raise PolicyError('prices require exact decimal strings or integers')
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result <= 0:
            raise ValueError()
        return Fraction(result)
    except Exception as exc:
        raise PolicyError('invalid positive finite price/unit amount') from exc


def _micros(value):
    scaled = value * 1_000_000
    return (scaled.numerator + scaled.denominator - 1) // scaled.denominator


def _references(data, provider, status, reviewed):
    refs = data['pricing_references'][provider]
    if type(refs) is not list or any(type(ref) is not str or not ref for ref in refs):
        raise PolicyError('invalid pricing references')
    official, account = False, False
    hosts = {'openai': {'openai.com', 'platform.openai.com', 'developers.openai.com'},
             'tavily': {'tavily.com', 'docs.tavily.com'}}[provider]
    for ref in refs:
        if ref.startswith('account-document:'):
            if not re.fullmatch(r'account-document:[A-Za-z0-9._-]+', ref):
                raise PolicyError('invalid account document reference')
            account = True
        else:
            parsed = urlsplit(ref)
            if parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.query:
                raise PolicyError('reference must identify an approved provider source')
            official = True
    if reviewed and ((status == 'VERIFIED_OFFICIAL' and not official) or
                     (status == 'VERIFIED_ACCOUNT_SPECIFIC' and not account)):
        raise PolicyError('missing applicable pricing reference')


def validate_policy(data, *, usable=False):
    """Validate all fields/relations; usable=True also requires reviewed status.

    The data is not repaired, default-filled, migrated, activated or fetched.
    """
    try:
        _fields(data, ROOT_FIELDS)
        if type(data['policy_schema_version']) is not int or data['policy_schema_version'] != POLICY_SCHEMA_VERSION:
            raise PolicyError('unsupported policy schema version')
        if data['state'] not in ('draft', 'reviewed') or type(data['state']) is not str:
            raise PolicyError('unknown policy state')
        reviewed = data['state'] == 'reviewed'
        if data['experiment_id'] != EXPERIMENT or type(data['experiment_id']) is not str:
            raise PolicyError('unsupported experiment identity')
        if data['currency'] != 'USD' or type(data['currency']) is not str:
            raise PolicyError('unsupported currency')
        if type(data['monetary_precision']) is not int or data['monetary_precision'] != 6:
            raise PolicyError('unsupported monetary precision')
        for field in ('budget_micro_usd', 'max_individual_reservation_micro_usd', 'max_aggregate_reserved_micro_usd'):
            _integer(data[field], maximum=SYSTEM_CAP_MICRO_USD)
        if not data['max_individual_reservation_micro_usd'] <= data['max_aggregate_reserved_micro_usd'] <= data['budget_micro_usd']:
            raise PolicyError('contradictory reservation/budget limits')
        if type(data['max_sdk_retries']) is not int or data['max_sdk_retries'] != 0:
            raise PolicyError('only zero SDK retries are supported')
        if type(data['max_concurrent_requests']) is not int or data['max_concurrent_requests'] != 1:
            raise PolicyError('only one unresolved request is supported')
        if type(data['evidence']) is not str or type(data['expires_at']) is not str:
            raise PolicyError('invalid review metadata')
        try:
            expiry = datetime.fromisoformat(data['expires_at'])
        except ValueError as exc:
            raise PolicyError('invalid review expiry') from exc
        if expiry.tzinfo is None:
            raise PolicyError('review expiry must include timezone')
        if reviewed and (not data['evidence'].strip() or expiry <= datetime.now(timezone.utc)):
            raise PolicyError('missing or expired pricing/bounds review')
        _fields(data['pricing_references'], {'openai', 'tavily'})
        for provider in ('openai', 'tavily'):
            _references(data, provider, 'UNVERIFIED', False)
        if type(data['openai']) is not dict:
            raise PolicyError('invalid OpenAI model map')
        if data['tavily'] is not None and type(data['tavily']) is not dict:
            raise PolicyError('invalid Tavily configuration')
        if reviewed and not data['openai'] and data['tavily'] is None:
            raise PolicyError('reviewed policy has no supported operation')
        for model, p in data['openai'].items():
            if type(model) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,199}', model):
                raise PolicyError('invalid model identifier')
            _fields(p, MODEL_FIELDS, CONTEXT_FIELDS)
            if p['pricing_status'] not in STATUSES:
                raise PolicyError('invalid pricing review status')
            if reviewed and p['pricing_status'] not in VERIFIED:
                raise PolicyError('unverified model pricing')
            if p['input_bound_mode'] not in ('utf8_text', 'provider_context'):
                raise PolicyError('unsupported input contract')
            for field in ('max_input_tokens', 'max_output_tokens', 'max_request_bytes', 'input_token_overhead'):
                _integer(p[field], nullable=not reviewed)
            n, out, overhead = p['max_input_tokens'], p['max_output_tokens'], p['input_token_overhead']
            if n is not None and overhead is not None and n <= overhead:
                raise PolicyError('input bound cannot cover framing overhead')
            if p['input_bound_mode'] == 'provider_context':
                if not CONTEXT_FIELDS <= p.keys():
                    raise PolicyError('missing provider-context contract')
                _integer(p['provider_context_tokens'], nullable=not reviewed)
                if type(p['context_evidence']) is not str or (reviewed and not p['context_evidence'].strip()):
                    raise PolicyError('unverified provider-context evidence')
                if p['provider_context_tokens'] != n:
                    raise PolicyError('provider-context maximum must match input bound')
            elif p.keys() & CONTEXT_FIELDS:
                raise PolicyError('context options unsupported in text-only mode')
            ip = _money(p['input_usd_per_million'], nullable=not reviewed)
            op = _money(p['output_usd_per_million'], nullable=not reviewed)
            if all(v is not None for v in (ip, op, n, out)) and _micros((n * ip + out * op) / 1_000_000) > data['max_individual_reservation_micro_usd']:
                raise PolicyError('model maximum exceeds individual reservation limit')
            _references(data, 'openai', p['pricing_status'], reviewed)
        p = data['tavily']
        if p is not None:
            _fields(p, SEARCH_FIELDS)
            if p['pricing_status'] not in STATUSES or (reviewed and p['pricing_status'] not in VERIFIED):
                raise PolicyError('unverified Tavily pricing')
            maximum = _money(p['basic_search_max_usd'], nullable=not reviewed)
            unit = _money(p['usd_per_credit'], nullable=not reviewed)
            credits = _money(p['max_credits_per_search'], nullable=not reviewed)
            if maximum is not None and _micros(maximum) > data['max_individual_reservation_micro_usd']:
                raise PolicyError('search maximum exceeds individual reservation limit')
            if all(v is not None for v in (maximum, unit, credits)) and maximum < unit * credits:
                raise PolicyError('search maximum does not cover declared credits')
            _references(data, 'tavily', p['pricing_status'], reviewed)
        if usable and not reviewed:
            raise PolicyError('draft policy cannot authorize spending')
        return data
    except PolicyError:
        raise
    except Exception as exc:
        raise PolicyError('malformed policy or field type') from exc


def load_policy_text(text, *, usable=False):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise PolicyError('duplicate policy field')
            result[key] = value
        return result
    try:
        data = json.loads(text, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(PolicyError('nonfinite JSON value')))
        return validate_policy(data, usable=usable)
    except PolicyError:
        raise
    except Exception as exc:
        raise PolicyError('malformed policy file') from exc


def load_policy_file(path, *, usable=False):
    try:
        return load_policy_text(Path(path).read_text(), usable=usable)
    except PolicyError:
        raise
    except Exception as exc:
        raise PolicyError('policy file unavailable') from exc
