# Final inactive budget policy — V7

**BUDGET_POLICY_READY: NO. Activation status: INACTIVE / BLOCKED DRAFT.**

Canonical machine-readable draft: [`policy_v5/canonical_budget_policy.draft.json`](policy_v5/canonical_budget_policy.draft.json), existing strict schema **1**, ledger schema **2**. It is unchanged from baseline: no verified new rate or numeric input/credit bound justified a policy edit. Identity/digest remain consistent with `policy_v5/draft_identity.json`: `79635e6c4f84a1bc733805484c835f6a7ffb2619efda2e6e3a767fc6ca3c7d3c` (production digest convention: sorted-key JSON). This is the sole policy format; no competing configuration was created.

## Existing canonical constraints

| Property | Existing inactive value / enforcement |
|---|---|
| State / expiry / review evidence | `draft`; expired 1970 timestamp; empty evidence. Cannot authorize or initialize a usable guard. |
| Experiment / currency / precision | `bounded-live-experiment-1`; USD; 6 decimal places; cumulative budget 1,000,000 micro-USD ($1.00). |
| Individual / aggregate reservation maxima | Both 1,000,000 micro-USD. These caps do not establish a per-operation maximum where pricing/units are null. |
| Outstanding concurrency / SDK retries | One unresolved request; zero SDK retries. SQLite transaction serializes admission. |
| Candidate model map | `gpt-5.4-mini`, `gpt-5.6-terra`; neither is an enabled/verified live operation while state is draft. |
| Candidate parameter maxima | Each output 2,048; request JSON 48,000 bytes. Mini `utf8_text` input maximum/overhead unresolved; terra `provider_context` input/context maximum/overhead unresolved. |
| Candidate prices | Input/output rates null, pricing status UNVERIFIED for both models. |
| Candidate Tavily | Basic search maximum USD, USD/credit and credit maximum null; UNVERIFIED. |
| References | Existing empty arrays; failed page access and API-contract source evidence are documented in the provider report, not represented as verified prices. |
| Ledger | Shared fixed canonical path `projects/bounded_spending.sqlite3`; absent. Active policy `projects/live_cost_policy.json` also absent. |

**Verified allowed live operations: none. Numeric production reservations: unavailable.** Candidate entries identify unresolved work; they are not allowances. Production loader `load_policy_file(..., usable=True)`, SpendingGuard construction, initialization and adapter authorization require a reviewed, complete, unexpired policy and valid canonical ledger.

Schema 1 expresses exact model allowlists through dictionary keys and provider enablement through the model map / Tavily object. Endpoints and permissible request shapes are enforced by compiled adapter/guard code: OpenAI HTTPS api.openai.com `/v1/` Responses.create only; Tavily `_search_tavily` fixes HTTPS api.tavily.com `/search`, basic depth, usage reporting and max_results≤20. No unsupported `allowed_endpoints`, application-retry-count or fallback field was invented to bypass strict validation. Model fallback is absent in effective Settings; an unknown alternate model is denied. Format/agent repair attempts remain possible only with separately retained capacity; there is no schema field promising zero application attempts beyond the initial one. If future authorization requires that restriction, it cannot be claimed through this schema alone.

Unknown prices/models, body overrides, hosted tools, unsupported endpoints, multimodal input, unreviewed hidden reasoning, policy corruption/expiry/draft and ambiguous usage fail closed at the existing boundaries. Exceeding actual units/cost is detected and freezes continuation after possible billing; it does not revoke the first external charge. Application reservations are not an OpenAI/Tavily account-level enforced hard invoice ceiling and do not constrain unrelated callers.

## Executed offline validation

Command (repository root):

```bash
.venv/bin/python -m pytest policy_v7/test_v7_policy.py policy_v5/test_policy_validation.py tests/test_spending_guard.py --policy-audit-output policy_v7/existing_policy_results -q -ra
```

Observed: **68 passed, 2 skipped/BLOCKED**, 1.42s; log `policy_v7/targeted_tests.log`. Components: 16 new V7 cases, 15 existing V5 passes plus 2 pricing-evidence blocks, 37 existing spending-guard cases. The earlier V7-only execution observed 15 passed in 0.71s before the Tavily request-builder positive case was added; the final combined command includes all 16. No historical audit suite was repeated. The full offline suite was not run: only reports and new isolated tests changed; shared production behavior did not change.

New tests use existing production loader, estimator/reservation code and adapter entry points, with temporary canonical path redirection and explicit **synthetic** review/rate fixtures. Real socket connections are forbidden. Actual installed OpenAI SDK serialization uses MockTransport; actual Tavily request builder uses a mocked HTTP opener. Dummy offline sentinel strings are not provider credentials. All initialized ledgers are temporary test fixtures; none grants a production allowance.

| ID | Scenario / observed result |
|---|---|
| P01 | Bounded synthetic mini structured output and terra native local-function request accepted through actual SDK/adapter; output cap and default tier serialized; exact maxima reserved. Additional P01b accepts actual Tavily basic builder with usage enabled through mocked opener. PASS in isolation; real canonical rates/bounds still BLOCKED. |
| P02 | Unknown model rejected before reservation/dispatch. PASS. |
| P03 | Unsupported SDK endpoint rejected before mock transport. PASS. |
| P04 | Missing price rejected by production policy loader. PASS. |
| P05 | UNVERIFIED declaration rejected from a reviewed usable policy. PASS; declarations in fixtures simulate a review and do not prove truth. |
| P06 | Input exceeds envelope, rejected before dispatch. PASS. |
| P07 | Output-limit override rejected before dispatch. PASS. |
| P08 | Nonzero SDK retry allowance rejected. PASS; existing spending tests also verify constructor disables SDK retries and unknown-completion retry loops send only once. |
| P09 | Uncovered model/fallback candidate rejected. PASS; existing fallback tests verify uncertainty stops schema/model fallback, with per-attempt reservations for allowed candidates. |
| P10 | Third $0.40 reservation rejected after two synthetic requests; full maxima retained. PASS. |
| P11 | Eight simultaneous reservation attempts admit exactly one outstanding $0.40 request atomically. PASS. |
| P12 | Unpriced hosted web-search tool and disabled Tavily search both rejected before dispatch. PASS. |
| P13 | Malformed JSON, unsupported version and wrong-root policy rejected. PASS. |
| P14 | Canonical draft structurally loads, usable loader/guard rejects, no policy/ledger created. PASS. |
| P15 | Invalid request through actual OpenAI adapter and actual Tavily builder: zero billable transport attempts. PASS. This is negative entry-point protection, not a demonstration of current official production cost bounds. |

Existing V5 P01/P15 remain explicitly skipped/BLOCKED because synthetic acceptance/arithmetic cannot verify an official-price canonical policy. No test was changed to call those external prerequisites passed. Existing spending tests additionally exercise crash/recovery, shared provider budget, excess actual costs, missing usage and provider timeouts.

The precise missing evidence and responsibility are in `LIVE_TEST_AUTHORIZATION_CHECKLIST.md`. No price was fabricated, validator weakened, production module edited, allowance activated or paid API request made.
