# Provider verification — supplied official pricing, 2026-10-29

**PRICING_VERIFIED: NO for complete applicable billing contracts.** The supplied public numeric rates and model limits are now recorded and usable for conditional calculations. **BUDGET_POLICY_READY: NO. LIVE_TEST_READY: NO.** A mini-only inactive candidate has complete numeric bounds, but account-rate applicability/entitlements and complete billing-contract applicability remain unverified. This does not discard the supplied evidence or assert that a paid call is needed to verify public prices.

## Evidence and provenance

`policy_v7/followup/user_supplied_pricing.json` records the user's transcription, exact official source URLs and verification date **2026-10-29**. It was independently checked for consistency with executable request options and exact arithmetic. It was **not independently downloaded**: the required proxy returned CONNECT 403 for both model pages, OpenAI pricing/cache and Tavily API-credit/search documentation. Newly supplied Tavily help/pricing URLs also returned CONNECT 403; failures are in `policy_v7/followup/tavily_new_sources_access.json`. No bypass, environment change, account probe or authenticated provider request occurred.

Previously retrieved official OpenAPI and provider SDK artifacts remain under `policy_v7/official_sources/`. They establish generic request/response structures and SDK behavior; they do not prove account rates, entitlement, or Tavily search defaults. User-supplied official excerpts are the source of the new numeric figures. No third-party compilation or existing heuristic model-price table was used as authority. No account contract, billing-plan record, entitlement record or authenticated historical response was supplied.

| Model | Public USD / million tokens: input / cached / output | Context / max output | Billing qualifications supplied |
|---|---|---|---|
| `gpt-5.4-mini` | 0.75 / 0.075 / 4.50 | 400,000 / 128,000 | Regional data-residency processing +10%. Candidate conservatively applies this to both input and output even if not applicable to the account. |
| `gpt-5.6-terra` | 2.00 / 0.20 / 12.00 | 1,050,000 / 128,000 | Over 272,000 input: entire request input ×2, output ×1.5. Default 30-minute cache writes ×1.25 ordinary input; optional 12-hour writes ×2.5. Exact interaction/overlap of cache-write and long-context billing is not independently established. |

Official sources: https://developers.openai.com/api/docs/models/gpt-5.4-mini ; https://developers.openai.com/api/docs/models/gpt-5.6-terra ; https://developers.openai.com/api/docs/guides/prompt-caching . Classification: **official-public figures supplied by user, not independently fetched; VERIFIED_ACCOUNT_SPECIFIC: NO**. Complete applicable billing-contract verification remains **PARTIALLY_VERIFIED**. A `VERIFIED_OFFICIAL` declaration in the draft refers to review of the supplied public numeric schedule, not account-specific pricing or activation approval.

Tavily supplied figures: basic search **1 credit**, advanced **2 credits**, Free Researcher **1,000 credits/month**, standard PAYG **$0.008/credit**. Conditional basic/advanced USD totals are **$0.008 / $0.016**, respectively. Sources: https://help.tavily.com/articles/6938147944-basic-vs-advanced-search-what-s-the-difference and https://www.tavily.com/pricing . The free allowance is not evidence of this account's available balance; no request is priced at zero.

## Exact request-path consistency

This is a targeted follow-up at baseline `f98351ea14c2772a104bab51f48d73d524a21bd7`, branch `policy-validator-repair`. Prior uncommitted follow-up reports/draft changes were preserved and updated. No completed repository audit was repeated. Production code is unchanged.

| Executable path | Actual parameters, defaults and limits | Applicable billable components / result |
|---|---|---|
| `OpenAIProvider.complete` → `_create` → `_request`, `src/llm/provider.py` | Synchronous `POST /v1/responses`; instructions, text input, strict JSON-schema format with JSON-object fallback; guard injects `service_tier=default` and policy output cap. | Standard/default token schedule, not Batch, flex, priority/fast or ultrafast. All model input, schema and generated JSON/reasoning consume token units. Mini-only candidate covers these with full-context input reservation. |
| `create_tool_response` → `_request`; native executor | Same endpoint with list input, local function definitions and `tool_choice=auto`; reasoning/output items returned in subsequent turns. Defaults use terra. | Context grows across turns; a character cap is not a billable-token maximum. Full provider-context reservation covers each allowed mini call independently; terra is excluded. Hosted tools are rejected, not assumed free. Local function descriptions/arguments/results consume model tokens; any actual Tavily execution needs a separate enabled credit allowance, absent here. |
| `_search_tavily`, `src/tools/search.py` | Exactly `{query,max_results,search_depth:"basic",include_usage:true}`; max_results integer 1..20; 30s timeout; no redirect following. No explicit auto_parameters/include_answer/include_images/topic/raw-content settings. | Supplied basic schedule is arithmetically consistent with $0.008 at standard PAYG. Server defaults, precise search usage schema and additional feature charges not verified; disabled in canonical candidate. |

Installed OpenAI 3.41.0 / httpx2 2.16.0 can serialize intended mini/terra requests in mocked tests. Dependencies remain broad `openai>=1.0`, not an exact lock. Tavily path uses Python urllib, not the public SDK inspected as supporting evidence. Official OpenAPI recognizes both exact model IDs, associates them with Responses, and states `max_output_tokens` includes visible and reasoning tokens. `truncation` defaults to disabled and rejects over-context input. Generic service-tier response can differ from the requested tier; the guard requires returned default tier and exact requested model identity or freezes continuation. Alias/snapshot response behavior and model-specific feature/entitlement records are not confirmed by the supplied excerpts. **DOCUMENTED_MODEL: YES (generic official API association); SDK_COMPATIBLE: YES offline; ACCOUNT_ACCESS_VERIFIED: NO.**

## Tavily usage/default/extra-charge findings

The installed application asks for `include_usage:true` and the public Tavily 0.8.5 source accepts/serializes that option and passes response JSON through. This confirms **request support**, not that this account/server guarantees a search response with `usage.credits` or that it includes every billable feature. README credit-usage examples apply to research results, not an authoritative search schema.

The guard requires a response object with numeric finite nonnegative `usage.credits`; missing/invalid/excess credits freeze continuation and retain exposure. That is post-dispatch protection, not proof that the initial charge was bounded. Mock responses cannot verify the server contract.

Still needed from official `/search` documentation: exact response shape and credit-unit semantics with include_usage, defaults for auto_parameters/depth and omitted answer/image/topic/content settings, whether any defaults cause additional credits, query/result-bound effects, and failure billing. The omitted SDK arguments are `None` and omitted from the wire; their server defaults cannot be inferred as false/zero. No advanced/answer/extract/research pricing was invented to cover unknown charges. **Full search billing contract: PARTIALLY_VERIFIED. Account plan/PAYG/free-credit applicability: UNVERIFIED.** Tavily remains disabled rather than assuming its cost is zero.

## Conservative exact cost bounds

`ceilµ(x)=ceil(1,000,000*x)`; use exact rationals/decimal strings. `policy_v7/followup/cost_bounds.json` stores the results.

**Mini-only candidate:** reserve all **400,000** provider-context tokens, not a guessed text-token conversion. Output is capped at **128 including reasoning**, below the supplied 128,000 provider maximum. Charge every input token at the higher uncached rate. Apply 10% residency uplift to both rates: **0.825 input / 4.95 output USD per million**.

```
R = ceilµ((400000*0.825 + 128*4.95)/1000000)
  = ceilµ(0.3306336 USD)
  = 330634 micro-USD = $0.330634
```

Reasoning is already in output units, not charged again. Cached input could lower actual charges; no discount is used. Request JSON is additionally capped at 4,096 UTF-8 bytes. The schema-required overhead field 256 is a local admission padding value, **not a certified tokenizer/framing bound**: the cost proof uses the entire provider context instead. Input+output context overlap is over-reserved conservatively by using full C plus separate output cap. The older 2,048-output candidate would reserve $0.340138 with the same rates; the new candidate uses 128 for the smallest verification attempt.

Mini cache-write surcharge is not supplied in its schedule; the independently retained API contract describes the new explicit cache options for gpt-5.6 and later. The current guard rejects caller cache options. The numeric mini calculation assumes the quoted standard token schedule covers the submitted request and that no unlisted mandatory component/contractual surcharge applies. Account applicability and completeness of the applied contract must be confirmed before marking this **VERIFIED_ENFORCEABLE**. Current bound status: **CONDITIONALLY_ENFORCEABLE**, not a hard invoice guarantee. No unsupported premium is guessed and no unlisted cost is silently certified as zero.

**Terra:** reserving full C=1,050,000 crosses the supplied 272,000 threshold. Even ignoring cache writes, maximum input/output rates 4/18 yield **$4.202304** with output cap 128. This alone exceeds the entire $1 budget. If the 30-minute cache-write rate replaces ordinary input for all tokens and compounds with the long-context input tier, the illustrative total is **$5.252304**; optional 12-hour replacement writes would be **$10.502304**. These examples are not extra additive charges: billing-component overlap must be verified before summing anything. Earlier retained API spec only describes 30m as supported, while the supplied excerpt mentions an optional 12h tier; current guard rejects specifying either cache option. This discrepancy does not affect exclusion: the no-write bound already fails. Terra is not a permitted $1 operation; using an arbitrary smaller N for hidden reasoning/context growth would not repair its bound.

**Retries, fallbacks and concurrency:** SDK max_retries=0 and redirects off. Application schema/model/agent repair attempts still cross the guard. For mini-only candidate, individual and aggregate caps both equal R, cumulative budget remains $1, one unresolved request at a time. Every permitted attempt reserves R; all reservations are retained, so **at most one attempt** can be admitted across processes, retries, failures or resumes. Model fallback is unset; uncovered models reject. A timeout can be billed and retains its full reservation. Usage-derived ledger cost is computed from conservative rates, not independently reconciled provider invoice data. Unsupported hosted tools/cache overrides fail before dispatch. Provider charges violating the assumed billing contract can exceed estimates before detection; future freeze cannot reverse that charge.

Account entitlements/rates were not probed. Supplied public rates do not establish account contracts. The narrow candidate is financially prepared only under its explicit public-rate assumptions; the full default research path (mini + terra + Tavily) remains unsupported under $1. No activation or paid execution occurred.
