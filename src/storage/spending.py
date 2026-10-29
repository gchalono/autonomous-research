"""Durable, fail-closed $1 experiment reservations, not a provider invoice cap.

Only the production adapters may select the canonical experiment ledger.
Generic transport callbacks are trusted injection points for isolated offline
validation; they are not a sandbox for arbitrary Python code.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from fractions import Fraction

from .policy import PolicyError, validate_policy, load_policy_file


class SpendingBlocked(RuntimeError):
    pass


ROOT = Path(__file__).resolve().parents[2] / 'projects'
POLICY_PATH = ROOT / 'live_cost_policy.json'
LEDGER_PATH = ROOT / 'bounded_spending.sqlite3'
CAP = 1_000_000
SCHEMA_VERSION = 2
EXPERIMENT_ID = 'bounded-live-experiment-1'
STATES = {'reserved', 'dispatching', 'reported', 'uncertain',
          'failed_before_dispatch', 'unresolved'}


def micros(value):
    try:
        if isinstance(value, bool):
            raise ValueError()
        if isinstance(value, Fraction):
            rational = value
        else:
            d = Decimal(str(value))
            if not d.is_finite():
                raise ValueError()
            rational = Fraction(d)
        if rational < 0:
            raise ValueError()
        scaled = rational * 1_000_000
        return (scaled.numerator + scaled.denominator - 1) // scaled.denominator
    except Exception as exc:
        raise SpendingBlocked('invalid monetary amount') from exc


def token_cost(i, ip, o, op):
    return (i * Fraction(ip) + o * Fraction(op)) / 1_000_000


def digest(policy):
    return hashlib.sha256(json.dumps(policy, sort_keys=True, allow_nan=False).encode()).hexdigest()


class SpendingGuard:
    def __init__(self, path, policy):
        self.path = Path(path)
        try:
            validate_policy(policy, usable=True)
            self.policy = json.loads(json.dumps(policy, allow_nan=False))
            self.digest = digest(self.policy)
            self._check_review()
        except (SpendingBlocked, PolicyError) as exc:
            raise SpendingBlocked(str(exc)) from exc
        except Exception as exc:
            raise SpendingBlocked('invalid pricing review') from exc

    def _check_review(self):
        try:
            validate_policy(self.policy, usable=True)
        except PolicyError as exc:
            raise SpendingBlocked(str(exc)) from exc

    @classmethod
    def default(cls):
        try:
            return cls(LEDGER_PATH, load_policy_file(POLICY_PATH, usable=True))
        except SpendingBlocked:
            raise
        except Exception as exc:
            raise SpendingBlocked('BLOCKED_COST_ENFORCEMENT: policy/ledger must be provisioned and reviewed') from exc

    def require_canonical(self):
        """Prevent optional adapter injection from choosing another allowance."""
        if type(self) is not SpendingGuard or self.path.resolve() != LEDGER_PATH.resolve():
            raise SpendingBlocked('noncanonical experiment ledger')
        expected = SpendingGuard.default()
        if self.digest != expected.digest:
            raise SpendingBlocked('canonical policy mismatch')

    def initialize(self):
        """Explicit offline provisioning only; never creates/reset on dispatch."""
        self._check_review()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('xb'):
            pass
        with sqlite3.connect(self.path) as db:
            db.executescript('''
                PRAGMA synchronous=FULL;
                PRAGMA user_version=2;
                CREATE TABLE session (id INTEGER PRIMARY KEY CHECK(id=1), digest TEXT NOT NULL,
                    cap INTEGER NOT NULL CHECK(cap=1000000), blocked TEXT,
                    experiment TEXT NOT NULL);
                CREATE TABLE requests (id TEXT PRIMARY KEY, provider TEXT NOT NULL,
                    model TEXT NOT NULL, reserved INTEGER NOT NULL CHECK(reserved>0),
                    actual INTEGER, usage TEXT, state TEXT NOT NULL,
                    experiment TEXT NOT NULL, operation TEXT NOT NULL, created_at TEXT NOT NULL);
            ''')
            db.execute('INSERT INTO session VALUES (1,?,?,NULL,?)', (self.digest, CAP, EXPERIMENT_ID))

    def _validate(self, db):
        if db.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
            raise SpendingBlocked('unknown ledger schema version')
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise SpendingBlocked('corrupt ledger')
        sessions = db.execute('SELECT id,digest,cap,blocked,experiment FROM session').fetchall()
        if len(sessions) != 1:
            raise SpendingBlocked('invalid session count')
        sid, pinned, cap, blocked, experiment = sessions[0]
        if sid != 1 or pinned != self.digest or type(cap) is not int or cap != CAP or experiment != EXPERIMENT_ID:
            raise SpendingBlocked('session policy/cap/experiment mismatch')
        if blocked is not None and (not isinstance(blocked, str) or not blocked):
            raise SpendingBlocked('invalid session block')
        total = 0
        ids = set()
        for rid, provider, model, reserved, actual, usage, state, exp, op, created in db.execute('SELECT * FROM requests'):
            if not isinstance(rid, str) or len(rid) != 32 or any(c not in '0123456789abcdef' for c in rid) or rid in ids:
                raise SpendingBlocked('invalid/duplicate reservation identifier')
            ids.add(rid)
            expected_op = {'openai': 'responses.create', 'tavily': 'search.basic'}.get(provider)
            if not expected_op or op != expected_op or not isinstance(model, str) or not model or exp != EXPERIMENT_ID:
                raise SpendingBlocked('invalid reservation operation/experiment')
            if type(reserved) is not int or not 0 < reserved <= CAP or (actual is not None and (type(actual) is not int or actual < 0)):
                raise SpendingBlocked('invalid persisted monetary amount')
            total += reserved
            if state not in STATES:
                raise SpendingBlocked('unknown reservation state')
            stamp = datetime.fromisoformat(created)
            if stamp.tzinfo is None:
                raise SpendingBlocked('invalid reservation timestamp')
            parsed = json.loads(usage, parse_constant=lambda v: (_ for _ in ()).throw(ValueError('nonfinite usage'))) if usage is not None else None
            if parsed is not None and not isinstance(parsed, dict):
                raise SpendingBlocked('invalid usage record')
            if state in {'reserved', 'dispatching'} and (actual is not None or usage is not None):
                raise SpendingBlocked('unresolved reservation has settled usage')
            if state == 'reported':
                if actual is None or actual > reserved or not parsed:
                    raise SpendingBlocked('inconsistent reported charge')
                quantities = [parsed.get('input_tokens'), parsed.get('output_tokens')] if provider == 'openai' else [parsed.get('credits')]
                if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in quantities):
                    raise SpendingBlocked('invalid reported usage quantities')
                if provider == 'openai' and any(type(v) is not int for v in quantities):
                    raise SpendingBlocked('noninteger reported tokens')
                if provider == 'openai':
                    rates = self.policy['openai'][model]
                    derived = token_cost(quantities[0], Decimal(str(rates['input_usd_per_million'])),
                                         quantities[1], Decimal(str(rates['output_usd_per_million'])))
                else:
                    derived = Fraction(str(quantities[0])) * Fraction(Decimal(str(self.policy['tavily']['usd_per_credit'])))
                if micros(derived) != actual:
                    raise SpendingBlocked('reported usage/cost mismatch')
            if state in {'uncertain', 'unresolved'} and not blocked:
                raise SpendingBlocked('uncertainty without session block')
            if actual is not None and actual > reserved and not blocked:
                raise SpendingBlocked('overage without session block')
            if state == 'failed_before_dispatch' and (actual not in (None, 0) or usage is not None):
                raise SpendingBlocked('invalid pre-dispatch failure')
        if total > min(CAP, self.policy['budget_micro_usd'], self.policy['max_aggregate_reserved_micro_usd']):
            raise SpendingBlocked('inconsistent aggregate reservations')
        return blocked

    @contextmanager
    def transaction(self, check_policy=True):
        db = None
        try:
            if check_policy and digest(self.policy) != self.digest:
                raise SpendingBlocked('effective policy digest mismatch')
            db = sqlite3.connect(self.path.resolve().as_uri() + '?mode=rw', uri=True, timeout=10)
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            blocked = self._validate(db)
            yield db, blocked
            self._validate(db)
            db.commit()
        except SpendingBlocked:
            if db: db.rollback()
            raise
        except Exception as exc:
            if db: db.rollback()
            raise SpendingBlocked('spending ledger unavailable or invalid') from exc
        finally:
            if db: db.close()

    def reserve(self, provider, model, maximum):
        self._check_review()
        operation = {'openai': 'responses.create', 'tavily': 'search.basic'}.get(provider)
        if not operation or not isinstance(model, str) or not model:
            raise SpendingBlocked('unknown provider operation')
        amount = micros(maximum)
        if amount <= 0:
            raise SpendingBlocked('positive maximum cost required')
        if amount > self.policy['max_individual_reservation_micro_usd']:
            raise SpendingBlocked('individual reservation limit exceeded')
        with self.transaction() as (db, blocked):
            if blocked:
                raise SpendingBlocked('session blocked: ' + blocked)
            if db.execute("SELECT 1 FROM requests WHERE state IN ('reserved','dispatching') LIMIT 1").fetchone():
                raise SpendingBlocked('unreconciled request; review recovery before continuation')
            total = db.execute('SELECT COALESCE(SUM(reserved),0) FROM requests').fetchone()[0]
            if total + amount > min(CAP, self.policy['budget_micro_usd'], self.policy['max_aggregate_reserved_micro_usd']):
                raise SpendingBlocked('session budget exhausted')
            rid = uuid.uuid4().hex
            db.execute('INSERT INTO requests VALUES (?,?,?,?,NULL,NULL,?,?,?,?)',
                       (rid, provider, model, amount, 'reserved', EXPERIMENT_ID, operation,
                        datetime.now(timezone.utc).isoformat()))
        return rid

    def begin_dispatch(self, rid):
        with self.transaction() as (db, blocked):
            self._check_review()
            if blocked:
                raise SpendingBlocked('session blocked')
            if db.execute("UPDATE requests SET state='dispatching' WHERE id=? AND state='reserved'", (rid,)).rowcount != 1:
                raise SpendingBlocked('invalid or reused dispatch reservation')

    def fail_before_dispatch(self, rid):
        with self.transaction() as (db, _):
            if db.execute("UPDATE requests SET state='failed_before_dispatch' WHERE id=? AND state='reserved'", (rid,)).rowcount != 1:
                raise SpendingBlocked('invalid pre-dispatch failure transition')
        # No refund, even for a known local failure: conservative allowance.

    def finish(self, rid, actual=None, usage=None, error=None):
        problem = error
        amount = None if actual is None else micros(actual)
        if amount is not None and amount > 2**63 - 1:
            usage = dict(usage or {}, estimated_micro_usd_out_of_range=str(amount))
            amount = None
            problem = problem or 'reported cost outside ledger integer range'
        with self.transaction() as (db, _):
            row = db.execute('SELECT reserved,state FROM requests WHERE id=?', (rid,)).fetchone()
            if row is None or row[1] != 'dispatching':
                raise SpendingBlocked('invalid or duplicate settlement')
            if amount is None or not isinstance(usage, dict) or not usage:
                problem = problem or 'missing usage/cost'
            if amount is not None and amount > row[0]:
                problem = 'reported cost exceeds reservation'
            db.execute('UPDATE requests SET actual=?,usage=?,state=? WHERE id=?',
                       (amount, json.dumps(usage, allow_nan=False), 'uncertain' if problem else 'reported', rid))
            if problem:
                db.execute('UPDATE session SET blocked=? WHERE id=1', (problem,))
        if problem:
            raise SpendingBlocked(problem)

    def snapshot(self):
        """Forensic read: can expose integrity errors, never authorizes dispatch."""
        error = None
        try:
            with self.transaction(check_policy=False):
                pass
        except SpendingBlocked as exc:
            error = str(exc)
        try:
            with sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True) as db:
                columns = ['id','provider','model','reserved_micro_usd','reported_micro_usd',
                           'usage','state','experiment','operation','created_at']
                rows = [dict(zip(columns, row)) for row in db.execute('SELECT * FROM requests')]
                blocked = db.execute('SELECT blocked FROM session WHERE id=1').fetchone()[0]
            return {'cap_micro_usd': CAP, 'budget_micro_usd': self.policy.get('budget_micro_usd'), 'blocked': blocked, 'integrity_error': error,
                    'financially_unresolved': any(r['state'] in {'reserved','dispatching','uncertain','unresolved'} for r in rows),
                    'requests': rows}
        except Exception as exc:
            raise SpendingBlocked('ledger unreadable for forensic snapshot') from exc

    @staticmethod
    def _check_sdk_transport(transport):
        resource = getattr(transport, '__self__', None)
        client = getattr(resource, '_client', None)
        if client is not None and type(client).__module__.startswith('openai'):
            endpoint = client.base_url
            if endpoint.scheme != 'https' or endpoint.host != 'api.openai.com' or endpoint.path != '/v1/' or endpoint.port not in (None, 443) or endpoint.query or endpoint.fragment:
                raise SpendingBlocked('unreviewed SDK endpoint')
            if getattr(client, 'max_retries', None) != 0 or getattr(getattr(client, '_client', None), 'follow_redirects', True):
                raise SpendingBlocked('SDK retries/redirects are not disabled')
            if type(resource).__name__ != 'Responses' or getattr(transport, '__name__', '') != 'create':
                raise SpendingBlocked('unsupported SDK operation')

    def invoke_openai(self, transport, kwargs):
        try:
            kwargs = json.loads(json.dumps(kwargs, allow_nan=False))
            self._check_sdk_transport(transport)
            allowed = {'model','instructions','input','text','tools','tool_choice'}
            if not isinstance(kwargs, dict) or set(kwargs) - allowed:
                raise SpendingBlocked('unsupported request option/body override')
            model = kwargs['model']
            p = self.policy['openai'][model]
            n, out = p['max_input_tokens'], p['max_output_tokens']
            overhead = p.get('input_token_overhead', 256)
            if any(type(v) is not int or v <= 0 for v in (n,out,p['max_request_bytes'],overhead)):
                raise ValueError()
            ip, op = Decimal(str(p['input_usd_per_million'])), Decimal(str(p['output_usd_per_million']))
            if not all(v.is_finite() and v > 0 for v in (ip,op)):
                raise ValueError()
            if any(t.get('type') != 'function' for t in kwargs.get('tools', [])):
                raise SpendingBlocked('unpriced hosted tools forbidden')
            raw = json.dumps(kwargs, ensure_ascii=False, allow_nan=False).encode()
            if len(raw) > p['max_request_bytes'] or len(raw) + overhead > n:
                raise SpendingBlocked('request exceeds reviewed input envelope')
            mode = p.get('input_bound_mode', 'utf8_text')
            if mode not in {'utf8_text', 'provider_context'}:
                raise SpendingBlocked('unknown input bound contract')
            if mode == 'provider_context' and (type(p.get('provider_context_tokens')) is not int or p['provider_context_tokens'] != n or not isinstance(p.get('context_evidence'), str) or not p['context_evidence'].strip()):
                raise SpendingBlocked('unverified provider context bound')
            def check_content(value):
                if isinstance(value, dict):
                    if value.get('type') in {'input_image','input_file','input_audio','item_reference'} or any(k in value for k in ('file_id','image_url')) or (mode != 'provider_context' and (value.get('type') == 'reasoning' or 'encrypted_content' in value)):
                        raise SpendingBlocked('unbounded multimodal/hidden input forbidden')
                    for v in value.values(): check_content(v)
                elif isinstance(value, list):
                    for v in value: check_content(v)
            check_content(kwargs)
            maximum = token_cost(n, ip, out, op)
        except SpendingBlocked:
            raise
        except Exception as exc:
            raise SpendingBlocked('unknown/unbounded model pricing or token limits') from exc
        SpendingGuard.require_canonical(self)
        rid = self.reserve('openai', model, maximum)
        self.begin_dispatch(rid)
        try:
            self._check_review()
            resp = transport(max_output_tokens=out, service_tier='default', **kwargs)
        except Exception as exc:
            self.finish(rid, error='provider exception: ' + type(exc).__name__)
            raise
        usage = getattr(resp, 'usage', None)
        i, o = getattr(usage,'input_tokens',None), getattr(usage,'output_tokens',None)
        if any(type(v) is not int or v < 0 for v in (i,o)):
            self.finish(rid,error='missing or invalid provider token usage')
        actual = token_cost(i, ip, o, op)
        error = 'token limit exceeded' if i > n or o > out else None
        if getattr(resp,'model',None) != model or getattr(resp,'service_tier',None) != 'default':
            error = 'unpriced response model or service tier'
            actual = None
        self.finish(rid,actual,{'input_tokens':i,'output_tokens':o,
                              'model':getattr(resp,'model',model),'service_tier':getattr(resp,'service_tier','default')},error=error)
        return resp

    def invoke_tavily(self, transport):
        try:
            p = self.policy['tavily']
            maximum = p['basic_search_max_usd']
            unit = Decimal(str(p['usd_per_credit']))
            if not unit.is_finite() or unit <= 0:
                raise ValueError()
        except Exception as exc:
            raise SpendingBlocked('unbounded Tavily pricing') from exc
        SpendingGuard.require_canonical(self)
        rid = self.reserve('tavily','basic',maximum)
        self.begin_dispatch(rid)
        try:
            self._check_review()
            data = transport()
        except Exception as exc:
            self.finish(rid,error='Tavily exception: '+type(exc).__name__)
            raise
        usage = data.get('usage') if isinstance(data,dict) else None
        credits = usage.get('credits') if isinstance(usage,dict) else None
        if type(credits) not in (int,float) or not math.isfinite(credits) or credits < 0:
            self.finish(rid,error='missing/invalid Tavily credit usage')
        self.finish(rid,Fraction(str(credits))*Fraction(unit),{'credits':credits},
                    error='search credit limit exceeded' if Fraction(str(credits)) > Fraction(str(p['max_credits_per_search'])) else None)
        return data
