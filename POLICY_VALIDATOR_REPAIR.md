# Policy-validator repair — V6

**POLICY_VALIDATOR_READY: YES** · **PRICING_VERIFIED: NO** · **LIVE_TEST_READY: NO**

The two V5 schema defects are repaired. The two evidence-blocked cases remain external prerequisites; they were not converted into synthetic pricing successes. The complete offline run passed: **284 passed, 2 pricing-evidence cases skipped/BLOCKED, 1 paid live test deselected**. No paid requests, production allowance initialization, environment changes, deployment, publication or commit occurred.

## Baseline and original findings

HEAD remains `1b2f809911445cfb46cea8a1c228993e8d30fe2a`, with preexisting uncommitted work preserved. Original source copies, hashes, status and the four-case failure trace are in `policy_v6/baseline/`.

| Original ID | Before repair | Cause | After repair |
|---|---|---|---|
| Q01[unsupported_field0] | FAIL: arbitrary root field accepted | Loader had no field whitelist | PASS: unknown fields rejected before guard use |
| Q01[unsupported_field1] | FAIL: policy_schema_version=999 accepted | No policy-version contract; field ignored | PASS: only integer policy version 1 accepted |
| P01 complete canonical policy | BLOCKED/skipped | No complete, reviewed authoritative pricing/input policy | Remains external BLOCKED; schema-only inactive draft now validates, but is not usable for spending |
| P15 documented cost maximum | BLOCKED/skipped | No official production prices/units/contracts to compare | Remains external BLOCKED; fixture arithmetic is not provider evidence |

The original P01, P15 and parameterized Q01 test function bodies are unchanged, confirmed by AST comparison in `policy_v6/original_case_integrity.json`. Complete original sources were preserved before edits. Only the synthetic policy factory and negative fixture setup migrated to the stricter format; no original financial assertion was removed.

The old effective contract was documented before implementation in `policy_v6/SCHEMA_CONTRACT.md`: no explicit policy version, permissive top/nested dictionaries and largely deferred pricing validation. SQLite schema 2 did not constitute a policy schema.

## Minimal production changes

| File/functions | Change |
|---|---|
| **New `src/storage/policy.py`**: `validate_policy`, `load_policy_text/file`, strict field/type/price/reference helpers | Explicit version-1 contract; reject unknown/missing fields, malformed/duplicate JSON, invalid types, unsupported options and contradictory constraints; separate structural draft inspection from usable reviewed policies |
| `src/storage/spending.py`: constructor, `default`, `_check_review`, `initialize` | Validate actual file and programmatic policies eagerly; revalidate before authorization/initialization; no permissive fallback, implicit migration or draft allowance |
| Same: `reserve`, `_validate`, `snapshot` | Enforce per-policy individual and cumulative/aggregate limits, always capped by system $1; retain existing atomic durable lifecycle and show policy budget distinctly |
| Same: `invoke_tavily` | Enforce declared search-credit maximum even when reported dollar estimate would still fit an over-reserved amount |

No orchestration, provider architecture, endpoints, credentials, deployment files or dependencies were changed. The SQLite ledger schema stays **2**. Existing canonical path/experiment binding, exact rational arithmetic, no-refund handling, guarded client surface and retry/redirect restrictions remain intact.

Baseline-relative patch/inventory: `policy_v6/v6_source_changes.patch` and `policy_v6/diff_summary.json`. Normal Git diff also contains earlier user changes and omits some formerly untracked files; it is not the isolated V6 delta. Test fixture changes are explicit in the patch.

## Supported policy contract

Only **policy_schema_version = integer 1** is supported. Missing versions, strings, booleans, floats, future versions and unknown keys are rejected. There is no implicit legacy mode.

### Required root fields

| Field | Type/range/meaning |
|---|---|
| `policy_schema_version` | Integer 1 exactly |
| `state` | `draft` or `reviewed`; neither value grants user spending authorization |
| `experiment_id` | Existing fixed string `bounded-live-experiment-1` |
| `currency` / `monetary_precision` | `USD` / integer 6; integer micro-USD with upward rounding |
| `budget_micro_usd` | Integer 1..1,000,000; cannot raise system ceiling |
| `max_individual_reservation_micro_usd` | Positive integer, at most aggregate cap |
| `max_aggregate_reserved_micro_usd` | Positive integer, at most budget; applies to all retained reservations, not just currently outstanding rows |
| `max_concurrent_requests` | Integer 1 only, matching current fail-closed single-unresolved-request mechanism |
| `max_sdk_retries` | Integer 0 only, matching actual SDK behavior |
| `evidence` | String; reviewed policy requires nonempty review evidence |
| `expires_at` | ISO timestamp string with timezone; reviewed policy must be unexpired |
| `pricing_references` | Exact keys `openai`, `tavily`, each a list of provider-appropriate HTTPS references or account-document identifiers |
| `openai` | Exact model-name allowlist map; empty disables OpenAI |
| `tavily` | Search configuration object, or null to disable Tavily |

A reviewed policy must enable at least one supported operation. Cross-field rule: `individual <= aggregate <= budget <= 1,000,000`. All limits are enforced in the existing admission/ledger path. Smaller budgets and aggregate/individual caps are supported and independently tested; unsupported higher concurrency/retry settings are rejected rather than merely recorded.

### OpenAI model entries

Required: `max_input_tokens`, `max_output_tokens`, `max_request_bytes`, `input_token_overhead`, `input_bound_mode`, `input_usd_per_million`, `output_usd_per_million`, `pricing_status`.

Reviewed integer bounds must be positive; input allowance must exceed explicit framing overhead. No safety-critical overhead/mode field is default-filled by the validator. The byte ceiling and input/overhead ceiling are both enforced, so the effective serialized ceiling is their minimum.

`input_bound_mode` is `utf8_text` or `provider_context`. Context mode additionally requires **both** `provider_context_tokens` equal to the input allowance and nonempty string `context_evidence`. These context fields are rejected in text-only mode. The reviewed maximum input/output cost must fit the individual reservation cap using exact upward-rounded arithmetic.

Model identifiers have a bounded plain-name syntax and must be exact allowlist keys. This is not a remote model-availability lookup or proof of provider pricing; account/model applicability remains external. Endpoints are the existing compiled HTTPS OpenAI Responses endpoint. A policy cannot configure an arbitrary endpoint, service tier or hosted feature; such unknown fields are rejected.

### Tavily search entry

Required: `basic_search_max_usd`, `usd_per_credit`, `max_credits_per_search`, `pricing_status`. The maximum must cover declared credits times unit price and fit the individual cap. Returned credits above the declared unit maximum freeze continuation even if the dollar estimate fits. The actual adapter remains basic POST Search with its existing parameter limits; no advanced/crawl/map service was added.

### Pricing, references and unsupported constraints

Prices and credit amounts are positive finite **decimal strings or integers**. JSON floating-point price literals, booleans, zero/free-price assumptions, negatives and nonfinite values are unsupported and rejected. Integer budget precision avoids binary rounding; original exact rational cost arithmetic remains in use.

Review-status declarations are VERIFIED_OFFICIAL, VERIFIED_ACCOUNT_SPECIFIC, PARTIALLY_VERIFIED, UNVERIFIED or CONTRADICTED. A usable reviewed operation requires one of the two VERIFIED declarations, complete bounds/prices and an appropriate reference. Official references must identify approved provider HTTPS hosts without credentials/query secrets; account-specific declarations require an `account-document:` identifier. Disabled providers do not require enabled-operation price declarations.

These checks validate **declaration completeness and reference format/provider association**, not the factual contents of a pricing page. A status string or URL cannot establish true current/account pricing. Official source review remains mandatory before production activation. Synthetic tests explicitly simulate review declarations; they do not verify provider prices.

Per-policy `max_search_calls`, `max_tool_calls`, arbitrary application retry counts, custom endpoint fields and all other unimplemented options are rejected. Existing finite workflow loops and independently reserved repairs remain; no new call-count architecture was invented. Unknown fields at every supported dictionary level are rejected.

`load_policy_text/file` also rejects duplicate keys, nonfinite JSON constants, wrong root types and malformed data. Validation performs no network access or ledger creation.

## Integration and enforceability

Both actual production policy loading and direct `SpendingGuard` construction require usable reviewed data. Effective object policies are revalidated before reservation and initialization; invalid mutations cannot bypass the guarded adapter, exposed client or helper paths. Canonical policy loading never falls back to old settings prices or a permissive format.

The existing SQLite transaction enforces retained aggregate and budget ceilings; individual caps are checked before committing admission. One-use dispatch, unknown-usage retention, crash recovery and no automatic refunds were preserved. Missing/corrupt/version-incompatible ledgers do not become fresh allowances.

Draft policies can be inspected with `validate_policy(..., usable=False)`. They cannot construct a usable guard, initialize a ledger or dispatch. A reviewed state is an eligibility declaration, **not activation authorization**; user approval and the existing explicit provisioning boundary remain separate.

## Compatibility and explicit migration

Unversioned legacy dictionaries are no longer accepted, even when their old rates were positive and the expiration future. Their safety-critical defaults/unknown fields were not an enforceable format. There was no active production policy or ledger in this workspace to migrate, and none was created.

Required offline migration steps:

1. Preserve the original file, digest and any ledger/history; quiesce writers. Never delete/reinitialize a ledger to obtain a fresh budget.
2. Add the exact version/state/identity/currency/precision/budget/individual/aggregate/retry/concurrency fields above. Explicitly supply model overhead/mode, review statuses/references and Tavily maximum credits. Convert intended decimal prices to exact quoted decimal strings, without changing their economic values.
3. Remove unsupported fields rather than assuming they are enforced. Reverify actual rates, input contracts and account applicability; do not label old estimates verified automatically.
4. Keep unresolved configurations in `draft`. Validate structure offline, then validate reviewed eligibility only after evidence is complete. No automatic activation is performed.
5. If an existing ledger is bound to the old policy digest, leave it blocked until a separately reviewed migration preserves every retained/uncertain exposure and reconciles historical cost bases. Merely editing the digest, dropping rows or recreating the database is unsafe. No production ledger migration tool was introduced here.

Historical **test fixtures only** were explicitly migrated by `tests/policy_fixtures.py`, retaining numerical values and supplying simulated review metadata. This helper is never imported by production code. Existing negative tests now expect earlier constructor rejection where appropriate; zero-dispatch/no-file assertions remain or are strengthened.

A test-only polling heartbeat was added to the old async-concurrency case because this sandbox denies AF_UNIX `socket.send` used by asyncio's thread wakeup. No production async or network behavior changed; real async-to-thread calls and all monetary assertions remain. Diagnostics and compatibility details are in the test report.

## Inactive draft and remaining blockers

Updated existing draft: `policy_v5/canonical_budget_policy.draft.json`; identity metadata updated without adding ignored authorization fields. `policy_v6/draft_acceptance.json` records:

| State | Finding |
|---|---|
| SCHEMA_VALID | YES |
| ENFORCEMENT_VALID | YES for supported declared constraints and enforced draft exclusion; no claim that unresolved production request bounds are verified |
| PRICING_COMPLETE | NO: required real rates, units and input-contract evidence remain unknown |
| ACTIVATION_AUTHORIZED | NO |

The draft remains USD $1, with null unverified values, UNVERIFIED pricing declarations, empty source lists and draft state. No production policy/ledger exists. Current policy digest: `79635e6c4f84a1bc733805484c835f6a7ffb2619efda2e6e3a767fc6ca3c7d3c`.

| Remaining blocker | Exact action/information | Responsible party | Blocks |
|---|---|---|---|
| OpenAI prices and request contracts | Official current rows for gpt-5.4-mini and gpt-5.6-terra; default/cached/input/output/context-tier rates, Responses output/reasoning/input limits, framing or full-context and returned identity contract. Prior official URLs were inaccessible; no new prices were guessed | User/provider account owner supplies official material; engineer verifies | Pricing and live readiness; not validator readiness |
| Tavily units/account conversion | Official basic-search maximum credits for allowed parameters, include_usage contract and applicable plan/overage USD conversion | User/Tavily account owner; engineer verifies | Pricing and live readiness |
| Reviewed usable policy | Fill only verified bounds/prices/references; confirm worst-case feasibility within $1, including prior same-experiment exposure; validate reviewed eligibility | Engineer after evidence | Live readiness |
| Account permissions/connectivity | Exact-model inference and Tavily search permissions remain unverified; runtime bindings/proxy success are not proof of intended paid functionality | Account owner; guarded checks only during separately approved experiment | Live readiness |
| Activation/paid execution | Separate explicit approval for the reviewed policy and one cumulative allowance; no automatic reset/migration | User | Spending authorization; no permission granted here |

Public prices need not prove an account invoice or provider-enforced cap. Other account activity, compromised credentials and provider adjustments remain outside the application guard. This repair is not a formal verification or absolute invoice guarantee.
