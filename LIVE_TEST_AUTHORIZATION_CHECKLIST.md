# Live-test authorization checklist — V7

**PRICING_VERIFIED: NO**

**BUDGET_POLICY_READY: NO**

**LIVE_TEST_READY: NO**

No spending is authorized. A future YES would mean ready to request separate execution authorization, not permission to dispatch. Evidence date: 2026-10-29 UTC.

## Completed prerequisites

- Repository and expected baseline verified; working branch is `policy-validator-repair`. Existing unrelated untracked work preserved. No V7 commit/push/deployment.
- Executable operation inventory and effective configuration inspected without exposing secrets.
- Both exact model IDs recognized by official OpenAI OpenAPI Responses model definitions; intended generic request shapes construct/serialize in installed OpenAI 3.41.0 with mocked transport.
- Official response contract confirms output cap includes reasoning; usage details and actual service-tier behavior reviewed.
- Tavily exact application request observed offline: `/search`, basic depth, 1..20 results, usage reporting requested. Public SDK source corroborates accepted request parameter names; it does not supply pricing.
- Targeted offline validation: **68 passed, 2 pricing-evidence cases skipped/BLOCKED**, with real sockets prohibited. Canonical draft rejected as usable; production policy and spending ledger absent.
- Existing schema, provider adapters, spending guard and validator remain unchanged; no environment settings or credentials changed.

## Blockers and evidence needed

| Blocker | Missing fact | Evidence needed | Who must act | Blocks which decision |
|---|---|---|---|---|
| Official OpenAI pricing inaccessible | Standard input/output prices for `gpt-5.4-mini` and `gpt-5.6-terra`; cache read/write billing, long-context thresholds, reasoning/output treatment, other mandatory charges and billable failure semantics | Dated official export/copy of https://openai.com/api/pricing/ with those exact models and standard tier, applicable cache/long-context/tool footnotes; https://developers.openai.com/api/docs/guides/prompt-caching sections applicable to gpt-5.6 implicit cache writing. If account has contractual rates, redacted applicable rate schedule and billing terms identifying service, units and effective dates. | User/provider supplies source documents; reviewer derives all-in bounds. No Cloud setting change is requested. | PRICING_VERIFIED, BUDGET_POLICY_READY, LIVE_TEST_READY |
| Model-specific limits and request contracts inaccessible | Per-model input/context and output maximum, structured JSON/native function/reasoning support, framing bound or complete provider-context bound; model alias versus returned model identity | Official model pages https://developers.openai.com/api/docs/models/gpt-5.4-mini and https://developers.openai.com/api/docs/models/gpt-5.6-terra, their supported-feature/limits sections and documented response-identity semantics. If text-byte bound cannot be supported, use existing provider-context mode only with documented C and a reservation demonstrably ≤$1. | User/provider supplies exact official evidence; reviewer checks existing schema/enforcement, without production edits. | BUDGET_POLICY_READY, LIVE_TEST_READY; pricing applicability where context tiers apply |
| Tavily credit/price and server-default contract inaccessible | Maximum credits for this exact basic request, default auto-parameter/answer/image behavior, usage.credits semantics, effect of query size/result count, failure billing and applicable USD/credit/plan/overage | https://docs.tavily.com/documentation/api-credits credits-per-request and plan/pay-as-you-go sections; https://docs.tavily.com/documentation/api-reference/endpoint/search request/default/usage sections. Redacted account plan/order form if standard public rate does not apply. No assumed free credits. | User/provider supplies official records; reviewer derives K×U and determines whether current builder is bounded. | PRICING_VERIFIED, BUDGET_POLICY_READY, LIVE_TEST_READY |
| Account access uncertain | Account/project entitlement for exact models/Responses and Tavily basic search; effective contractual rates not proved by key presence | Redacted provider-console model-access/organization/project entitlement record or provider confirmation for both exact IDs and endpoint; Tavily plan/service entitlement. Alternatively a **later separately authorized** bounded verification step after policy readiness, explicitly addressing this uncertainty. No model-listing/probing request is authorized now. | Account owner/provider. | LIVE_TEST_READY until uncertainty resolved or addressed by separately authorized bounded step; account-specific pricing if required |
| Canonical draft incomplete | Verified numerical inputs and per-operation maxima compatible with schema and $1 cap | Complete preceding evidence, derive exact micro-USD reservations, update existing draft only, validate through production loader/estimator/adapter mocks. Recheck alias/tier response expectations. If required rates/components cannot be expressed or maxima exceed $1, stop that portion and propose narrower scope or separately authorized production remedy. | Reviewer after evidence supplied. | BUDGET_POLICY_READY, LIVE_TEST_READY |

These are external evidence/contract blockers, not a reason to repeat the completed validator audit. Public documentation access failed with proxy CONNECT 403; official public OpenAPI and package-source access worked through the required proxy. No bypass, repeated blind retry, third-party rate substitution or environment reconfiguration was used.

## Required authorization sequence after evidence resolves

1. Review supplied official sources and any redacted account contract; establish rates, units, context limits and credit maxima. Resolve any extra input cache-write charge without double-counting input/output units.
2. Complete only verified entries in the existing **inactive** draft, exclude unsupported operations, recalculate maximum reservations with exact arithmetic, and rerun the targeted offline tests. Reject an operation if its enforceable maximum cannot fit the $1 shared allowance. A narrower single-model structured verification can be proposed instead of assuming the full native research pipeline fits.
3. Present concrete final operation set, request bounds, retained per-attempt reservations, shared ledger identity, maximum total exposure and account-access handling for review. No model fallback is currently configured; schema/agent repair attempts consume fresh capacity and are not a promise of one request per task.
4. Obtain separate explicit authorization to provision/activate the canonical reviewed policy and single experiment ledger, and separate explicit authorization for the precisely bounded paid execution. Neither authorization is supplied by V7. Existing canonical loader rejects a missing policy/ledger; do not run smoke/live commands to discover pricing or account permissions.
5. Immediately before any authorized execution, recheck effective model/endpoint/SDK/configuration and source validity, preserve existing ledger history, and confirm no unrelated callers share an assumed provider cap. Do not reset the experiment ledger to replenish budget.

## Residual financial risk

The $1 limit is an application reservation cap subject to verified external billing contracts. It is not a provider-enforced invoice limit. Provider errors, timeouts and crashes can still be billed; retained reservations and fail-closed continuation protect future admission, not undo incurred charges. A provider charge beyond the documented bound can breach the estimate before detection. Cached-input discounts are not assumed, and new implicit cache-write billing must be resolved. Other account activity is outside the guard. No hard provider-level monetary guarantee is demonstrated.

**Smallest safe next action:** supply dated official pricing/model-limit/search-contract exports identified above, plus any applicable redacted account-rate terms. No API keys in chat. Review those documents offline before modifying the draft or considering any provider probe. No additional production implementation is authorized by this report.
