# Canonical inactive $1 policy — mini-only conditional candidate

**PRICING_VERIFIED: NO (complete account/applicable billing contract). BUDGET_POLICY_READY: NO. LIVE_TEST_READY: NO.** Supplied official-public numbers now support a concrete conservative candidate; unknown terms are not converted into an activation-ready policy.

Canonical file: `policy_v5/canonical_budget_policy.draft.json`; policy schema **1**, ledger schema **2**. No competing policy format or production-code change. Its state remains **draft** and production loader with `usable=True` rejects it. `projects/live_cost_policy.json` and `projects/bounded_spending.sqlite3` remain absent. All temporary reviewed copies/ledgers described below are offline test fixtures, not production allowances.

| Constraint | Inactive candidate |
|---|---|
| Budget | USD 1,000,000 micro-USD ($1 cumulative), six decimal places |
| Experiment | Existing shared `bounded-live-experiment-1` |
| Model / endpoint | `gpt-5.4-mini` only; compiled guard permits HTTPS api.openai.com `/v1/` Responses.create and default tier |
| Full input reservation | 400,000 tokens, `provider_context` mode, source and evidence text included |
| Output bound | 128 generated tokens including reasoning, injected by actual guard |
| Request byte cap | 4,096 UTF-8 JSON bytes, checked before transport |
| Input padding | 256 local admission units required by existing schema; not a tokenizer claim and not the basis for monetary reservation |
| Input/output rates | Exact strings `0.825` / `4.95` per million: supplied uncached schedule +10% uplift, no cache-read discount |
| Per-request reserved maximum | **330,634 micro-USD ($0.330634)**, upward-rounded from $0.3306336 |
| Aggregate retained reservation cap | **330,634 micro-USD**; enforces **at most one mini attempt**, despite overall $1 budget |
| Outstanding concurrency / SDK retries | One / zero |
| Terra / Tavily | No terra model entry; Tavily `null`, so both rejected |
| Hosted tools / cache override / unknown operation | Rejected by existing guard before dispatch; no price-zero assumptions |
| Review expiry | 2026-11-05 UTC, an operator-selected re-review deadline; `state:draft` blocks use regardless of date |

`policy_v5/draft_identity.json` contains the matching production digest, candidate operation, activation_ready=false and no currently eligible live operations. `VERIFIED_OFFICIAL` per-model metadata records review of the **user-supplied official public numeric schedule**, not independently fetched pages, account entitlements, account pricing or execution approval. The policy remains a **conditional draft** until the applicable billing-contract/account prerequisites in the checklist are addressed. A structurally valid policy declaration is not external evidence validation.

The 400,000-token reservation covers provider context growth without asserting that short prompts or 4KB requests have a verified byte-to-token ratio. Hidden reasoning input is only accepted in full provider-context mode. Local function definitions/call outputs consume model tokens already bounded by full context; the policy cannot distinguish structured-only versus local-function Responses through a new unsupported field. The proposed first execution sends **no tools**; hosted tools are blocked and actual Tavily dispatch is disabled. Caller-specified output caps, cache TTL/options, higher service tiers, body overrides and unknown models reject. No architecture/validator change was made.

All admitted mini attempts reserve the same full amount. Therefore a second format fallback, agent repair, model request or resumed caller cannot fit the aggregate cap even after a successful low-usage first call. Lower reported usage does not refund capacity. Timeouts retain exposure and freeze continuation; they are not assumed free. Exact model/tier mismatch or missing/excess usage also freezes. Ledger 'actual' values are usage-derived estimates at conservative rates, not verified invoices. The rule protects admission under the assumed documented contract, not against arbitrary provider overcharges or unrelated account activity.

## Executed offline validation

```bash
.venv/bin/python -m pytest policy_v7/followup/test_blocked_policy.py policy_v7/test_v7_policy.py policy_v5/test_policy_validation.py tests/test_spending_guard.py --policy-audit-output policy_v7/followup/pricing_policy_results -q -ra
```

Observed **79 passed, 2 skipped**; `policy_v7/followup/pricing_offline_tests.log`. Components: 11 current public-rate candidate cases, 16 prior V7 SDK/adapter cases, 15 existing V5 passes and 37 spending-guard cases. No full audit or full suite repeated. Two historical V5 functions unconditionally skip official-price assertions and retain their old missing-evidence text; those messages are not a fresh finding that the user supplied no prices. They were not rewritten or reported passed. Current candidate arithmetic and adapter/reservation coverage are provided by the new follow-up tests.

The 11 new cases verify: draft/digest/no activation; empty reviewed policy still rejects; supplied rate/uplift/full-context arithmetic; actual OpenAI adapter submits one capped/default-tier attempt and rejects a second while retaining full reserve; terra/Tavily never dispatch; five variants reject hosted tools/cache override/priority/output override/oversized input before dispatch; and even no-cache full-context terra exceeds $1 and is rejected by production validator.

For reviewed-copy tests only, the existing loader, cost estimator, canonical reservation checks and actual provider adapter are exercised against redirected temporary policy/ledger paths and mocked transports. A fabricated test review state does not prove account contract truth. Real network sockets are forbidden. An example valid-context mock reports 399,872 input +128 output tokens: usage-derived conservative cost 330,528 micro-USD; retained reservation remains 330,634 and a second attempt is blocked.

The existing V7 P01 SDK MockTransport checks actual installed SDK serialization for both configured model IDs; that protocol check does not permit terra in this candidate. Existing tests additionally cover retries, crash/recovery, missing usage, concurrency, exhaustion and external charges above estimates.

Access-failure evidence is retained in the follow-up directory alongside the current candidate and pricing validation; superseded empty-draft test artifacts are excluded from this preservation commit. Source excerpts/URLs/date and conditional terra/Tavily calculations are in the provider report. The verification phase did not activate allowances, make paid provider calls or change environment settings. Preservation commits do not authorize execution.
