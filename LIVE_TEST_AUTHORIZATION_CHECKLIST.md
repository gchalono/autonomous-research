# Remaining authorization prerequisites — supplied-price follow-up

**PRICING_VERIFIED: NO — complete applicable billing contract remains partial.**
**BUDGET_POLICY_READY: NO — concrete mini-only candidate remains conditional/inactive.**
**LIVE_TEST_READY: NO.**

The supplied official public numbers have been recorded and used, not discarded for lack of direct web access. What is missing is account/complete-contract applicability and Tavily's exact endpoint/default/usage contract. No provider probe is necessary merely to confirm supplied public arithmetic. No spending has been authorized.

## Completed

- Recorded exact mini/terra rates, cached rates, context/output limits, residency/long-context/cache-write multipliers and Tavily credits/PAYG figures with official URLs, source provenance and 2026-10-29 date.
- Checked consistency against executable Responses and basic-search builders; reused earlier official API/SDK evidence without repeating repository audits.
- Derived mini candidate reservation **$0.330634**, conservatively covering 400,000 input tokens at uncached rate plus 128 output/reasoning tokens and +10% uplift.
- Derived terra no-cache lower maximum **$4.202304** at full context: unsuitable for the $1 envelope even before write charges. Excluded terra.
- Kept Tavily disabled: its supplied PAYG arithmetic is verified conditionally, but server defaults, extra-credit semantics, include_usage search response guarantee and account plan are unverified.
- Updated existing schema-1 draft/identity only; no activation. Set aggregate cap equal to the mini per-attempt reservation, allowing at most one attempt under existing shared-ledger enforcement.
- Executed targeted offline checks: **79 passed, 2 preserved historical V5 assertions skipped**. Draft cannot load as usable; production policy/ledger absent. Source, guard and validator unchanged.

## Exact remaining blockers

| Blocker | Missing fact | Exact evidence needed | Who must act | Decision blocked |
|---|---|---|---|---|
| Mini account-rate / billing-contract applicability | Does this account use the supplied standard default-tier schedule across the permitted context range, with no mandatory charge outside covered token rates and the allowed 10% regional uplift? | Redacted account API pricing/standard-rate applicability record or applicable contract/rate schedule; relevant mini model-page/processing/cache footnotes if any qualify the supplied figures. No need to resend the numeric rates already recorded. Confirm any account surcharge/region treatment is covered. | Account owner/provider; reviewer then records applicable terms. | Complete PRICING_VERIFIED and BUDGET_POLICY_READY; LIVE_TEST_READY |
| Mini entitlement and model-specific API behavior | Exact account/project model entitlement, structured JSON support, and whether returned model/tier identifiers satisfy existing exact-match check | Dated redacted console/provider entitlement confirmation and official model-feature/response-identity documentation; an existing redacted response record can corroborate requested/returned model and tier. If access cannot be established offline, propose a **separately authorized, one-attempt verification** only after its financial assumptions are approved. | Account owner/provider; user separately authorizes any later verification. | LIVE_TEST_READY; not a reason to re-audit validator |
| Tavily search contract | With exact `{search_depth:"basic",include_usage:true,max_results:1..20}`, what response `usage.credits` is guaranteed, which defaults apply, and could additional features consume credits? | Official https://docs.tavily.com/documentation/api-reference/endpoint/search request-default and response-usage sections, plus credit footnotes for auto_parameters, depth, answer/images/content/topic and failure billing; official https://help.tavily.com/articles/6938147944-basic-vs-advanced-search-what-s-the-difference for depth credits. | User/provider supplies sections unavailable through proxy. | Adding Tavily; full research readiness. Does not require enabling it for mini-only verification. |
| Tavily account plan | Does standard $0.008 PAYG apply; are free credits available and are there plan-specific/overage terms? | Dated redacted plan/order-form/PAYG record corresponding to https://www.tavily.com/pricing . No free balance inferred from the published allowance. | Account owner/provider. | Adding Tavily and full research pricing; excluded from mini candidate. |
| Terra full-context maximum exceeds $1 | No missing numeric fact is needed to reject current full-context proposal: even supplied no-write maximum exceeds $1 | Keep excluded. A future narrower-input proposal would need an authoritative enforceable token bound that also covers reasoning continuation, plus cache/write/long-context overlap terms; do not pick an arbitrary N. | Reviewer/user only if future scope requires terra. | Existing default full research pipeline; not mini-only alternative. |

Direct independent retrieval remains unavailable (proxy CONNECT 403), including both supplied model pages and the new Tavily URLs. Logs identify every attempted source. User-provided official documentation/contract records can resolve evidence gaps without changing Cloud configuration. Account access and pricing were not queried with API keys. Key presence and configured secret readiness do not establish entitlement. **No keys in chat.**

## Smallest safe next action and conditional first live test

**Next action now:** provide/confirm the mini account's applicable standard-rate/processing terms and dated entitlement record, or specify the intended separately authorized access-verification step once financial applicability is accepted. Tavily/terra documentation can be deferred while those operations remain excluded. The concrete candidate and its offline evidence are ready for that review; current status remains blocked, not an instruction to spend.

If those prerequisites are resolved, re-review the existing inactive mini-only draft and rate validity (review expiry 2026-11-05 UTC). Proposed first execution is **one** synchronous mini Responses call with a tiny literal prompt/JSON schema, output cap 128 including reasoning, request JSON ≤4,096 bytes, default tier, no hosted or local tools, no Tavily, no terra, no model fallback, no SDK retries. The aggregate cap equals R=330,634 micro-USD, so schema fallback/repair/resume cannot send a second request. Budget remains cumulatively $1; the unused difference is not spendable capacity because of the lower aggregate cap.

This tests bounded dispatch/usage, not research quality; the 128-token cap may be consumed by reasoning before valid JSON is produced, with no second attempt allowed.

The policy model entry technically covers bounded local-function Responses too; schema 1 has no separate structured-only field. Their generated/input tokens fall within the same reservation, but the authorized first-test procedure must send no tools. No unsupported policy field or production change was introduced to imply otherwise.

Only after the prerequisites and final offline results are reviewed should separate authorization be requested for canonical provisioning and this exact paid attempt. No provisioning, activation, smoke test, account/model-listing call or paid request is authorized by this document. Never reset the shared ledger to replenish capacity.

## Residual financial risk

The reservation is an application-enforced bound **conditional on the applicable billing contract**, not a provider-enforced $1 invoice cap. Public rates do not establish account-specific contracts. Actual usage-derived ledger cost is calculated with conservative rates, not reconciled billing data. Unknown usage, failures/timeouts/crashes and response mismatches retain exposure and freeze continuation; they cannot undo a charge. Provider charges above the assumed bound can occur before detection; unrelated account activity is outside the guard. No hard monetary guarantee is claimed.
