# Final Acceptance Report — Phase 3 (Production Hardening)

**Repository:** `~/workspace/autonomous-research/`
**Date:** October 28, 2026
**Scope:** independent verification of the Phase 2 `CONDITIONALLY READY`
claims, hardening per the Master Prompt V2.0, and readiness gates.

## 1. Verified repository state

- Python 3.12.3; pydantic 2.14.1; openai SDK 3.40.0; pytest 9.2.0.
- Entry point `main.py` (run / status / report / resume / cancel).
- Modules: config, models/contracts, orchestration (states, engine,
  correction, claim_check), storage (database, artifacts), security
  (permissions), tools (base, search, retrieval, computation), llm
  (provider), agents (common, creator, evaluator, executor, auditor).
- Phase 2 claims checked and reproduced: 45-test baseline re-ran green
  before any Phase 3 change; strict-schema fix, claim analyzer,
  verification persistence, and full-re-execution wiring all present in
  code and covered by tests (not merely reported).
- New in Phase 3: `.gitignore` (`.env`, `.venv/`, `projects/` excluded),
  preflight budget estimation, runtime limit, transient-error recovery,
  model fallback with recorded actual model, structured run log,
  terminal-status mapping, extended claim outcomes, claim-verification
  appendix in final reports, search-cost tracking, completion banner
  and `AR_NOTIFY_CMD` hook, corrected model prices, final report on the
  `COMPLETED_WITH_LIMITATIONS` path.

## 2. Tests executed

Exact command (venv active, repo root):

```bash
.venv/bin/python -m pytest tests/ -q
```

| Run | Result | Runtime |
|---|---|---|
| Baseline (Phase 3 start, before changes) | 45 passed, 1 skipped | 5.53 s |
| Final (after all Phase 3 changes) | **67 passed, 1 skipped** | 5.40 s |

The 1 skip in both runs is the live-API end-to-end test, which requires
`AR_RUN_LIVE=1` and a real `OPENAI_API_KEY` — skipped by design, not by
omission. No test failed in the final run; no warnings attributable to
application code.

Test files: `test_orchestration.py`, `test_agents.py`,
`test_recovery.py`, `test_security.py`, `test_tools.py`,
`test_integration.py`, `test_adversarial.py` (Phase 2),
`test_hardening.py` (Phase 3, 13 tests),
`test_adversarial2.py` (Phase 3, 9 tests).

## 3. Real API compatibility results

No live API call was made (no credentials — see §9). Compatibility was
verified by:

- **SDK introspection** (openai 3.40.0): `responses.create` accepts
  `instructions`, `input`, `text.format`; `output_text` and
  `usage.input_tokens` / `usage.output_tokens` confirmed.
- **Strict-schema compliance:** every Pydantic contract transformed by
  `make_strict_schema` satisfies strict mode (all properties required,
  `additionalProperties: false`, no `default` keywords, no `$ref`
  remnants) — asserted by test, including the `{"$ref", "default"}`
  sibling form found during Phase 2 remediation.
- **Models re-verified Oct 28, 2026** (fresh check, not relying on Phase
  2): `gpt-5.4-mini` and `gpt-5.6-terra` remain current model ids.
  `gpt-5` family remains deprecated (shutdown announced Dec 11, 2026)
  and is not used.
- **Prices re-verified Oct 28, 2026** against multiple third-party
  compilations of OpenAI's pricing page (agreeing): gpt-5.4-mini
  $0.75/$4.50, gpt-5.6-terra $2.00/$12.00 per 1M input/output tokens.
  These replaced Phase 2 placeholder estimates in `src/config.py`.
  Prices are still estimates for budget math; the provider's bill
  governs, and long-context (>272K input tokens) rates run ~2x/1.5x.
- **Model fallback:** implemented and unit-tested with a fake client
  (model-not-found → configured fallback executes; `models_used`
  records the fallback, `last_response_id` captured). Never silently
  substitutes an unconfigured model.
- **Structured-output fallback:** strict → plain JSON mode on schema
  rejection, with Pydantic validation + one repair retry still
  enforcing the contract. Malformed output is never silently accepted.

## 4. Models and search tools actually used

- **Live models used: none.** No live run exists; configured models are
  creator/evaluator `gpt-5.4-mini`, executor/auditor `gpt-5.6-terra`.
- **Live search used: none.** Tool behavior verified: Tavily path via
  mocked HTTP; DuckDuckGo keyless endpoints verified (Phase 1 and again
  by the stub demo's real fetch failing) to return bot-guard pages, in
  which case the tool fails honestly and the executor records the
  limitation instead of fabricating sources.

## 5. Cost accounting

- **Total validation spending: $0.00.** No paid API call was made in
  Phase 3, because no spending ceiling was authorized. This is
  compliance with the mandate (§7.4, §19), not an oversight.
- Per-project budget guard: $10 default, enforced by (a) preflight
  estimation before every call, (b) a spent-vs-budget check before
  every completed call, (c) transcript cap (60k chars), (d) bounded
  iterations/revisions/corrections, (e) runtime limit (3600 s).
- Stub demo runs report estimated costs (e.g. $0.0066 for a stub run)
  computed from stub token counts at configured prices — these are
  mechanical estimates for testing the accounting path, not observed
  provider billing, and are labeled as such wherever reported.
- Estimated live cost per project at verified prices: roughly $1–5 for
  a typical run including correction cycles. Proposed total validation
  ceiling for the live phase: **$30** (up to 3 attempts at the $10
  per-project cap), pending user approval.

## 6. Source-verification results (mechanical, stub-driven)

Code verification (re-fetch + passage sample) exercised across: confirmed
passage, not-found passage, unreachable source, verification cap,
fabricated citation, unrelated page content, misleading snippet,
fabricated quotation, inaccessible page. In every case the resulting
state transition and artifact matched the expected behavior (see §7).
Semantic entailment (passage meaning vs. claim) remains auditor-LLM
judgement, isolated and instructed — see defect D-10.

## 7. Adversarial test results (spec §10, 15 cases)

| # | Case | Result | Evidence |
|---|---|---|---|
| 1 | Fabricated citation | PASS | VERIFIED claim on nonexistent URL → `COMPLETED_WITH_LIMITATIONS`, open CRITICAL |
| 2 | Real URL, unrelated content | PASS | Passage NOT_FOUND → limitations path |
| 3 | Genuine passage not supporting claim | PASS | Auditor semantic rejection → correction cycle (Phase 2 suite) |
| 4 | Incorrect arithmetic | PASS | Auditor flags bad margin → 1 correction, then COMPLETED |
| 5 | Missing transaction fee | PASS | Auditor flags omitted 12% fee → correction task artifact preserves it |
| 6 | Unsupported profitability assumption | PASS | INFERRED profit claim with no sources → limitations path |
| 7 | Outdated pricing | PASS | Stale-price limitation preserved verbatim in final report |
| 8 | Contradictory sources | PASS | Auditor names conflict → correction cycle |
| 9 | Inaccessible webpage | PASS | UNREACHABLE in final report; VERIFIED claim blocked |
| 10 | Misleading search snippet | PASS | Snippet absent from page → NOT_FOUND → limitations path |
| 11 | Fabricated quotation | PASS | Invented quote absent from page → limitations path |
| 12 | Missing source attribution | PASS | Claim with no sources → MAJOR issue → limitations path (Phase 2 suite) |
| 13 | Prompt injection in retrieved content | PASS | Injection scanned, wrapped as untrusted data, treated as data only |
| 14 | False auditor approval | PASS | APPROVE with open CRITICAL/MAJOR → downgraded to corrections (Phase 2 suite) |
| 15 | Incorrect claim-to-source mapping | PASS | Dangling source id → MAJOR issue → limitations path (Phase 2 suite) |

No case passed on an LLM's say-so: every PASS above is an asserted state
transition, artifact content, or issue record.

## 8. Recovery test results (spec §11)

| Scenario | Result |
|---|---|
| New project / revision / rejection / execution / audit rejection / correction / completion | PASS (existing + new suites) |
| Cancellation (mid-workflow state) | PASS — no further LLM calls after cancel |
| Interrupted execution → resume | PASS — stored steps reused, zero duplicate LLM calls |
| API timeout / rate limit | PASS — transient error keeps project resumable with `transient_error`; permanent auth error still FAILS |
| Malformed model output | PASS — one repair retry, then safe failure |
| Database interruption / checkpoint integrity | PASS — per-step checkpoints, atomic artifact writes, versioned prompts/audits never overwritten |
| Budget exhaustion | PASS — terminal `BUDGET_EXHAUSTED`, intermediate artifacts preserved, resume is a no-op |
| Runtime limit | PASS — fails with explicit reason, artifacts preserved |
| Idempotency / duplicate costs | PARTIAL — step outputs idempotent; external API calls may repeat after a crash mid-call (all shipped tools are read-only, so repeats are harmless; documented as D-15) |

## 9. Live research findings

**None.** The genuine live end-to-end project (commodity arbitrage,
§12 of the mandate) was NOT executed: no `OPENAI_API_KEY` and no
`TAVILY_API_KEY` were present in the environment (presence checked only;
no values read or stored), no `.env` file exists, and no total
validation spending ceiling has been authorized. There is therefore no
genuine live research report to link; the stub demo reports in
`projects/` are explicitly canned output and must not be presented as
research. Exact live commands and pass criteria are in
`LIVE_TEST_RESULTS.md`.

## 10. Unresolved defects

No unresolved CRITICAL or HIGH defects remain. Open items (from
`DEFECT_REGISTER.md`):

- D-10 (MEDIUM): semantic claim entailment rests on the auditor LLM.
- D-11 (MEDIUM): no live validation — the blocking item for this phase.
- D-12 (LOW): prices are estimates; provider bill governs.
- D-13 (LOW): cancellation honored between phases, not mid-LLM-call.
- D-14 (LOW): keyless search unreliable; Tavily key recommended.
- D-15 (INFO): exact-once execution not claimed for external calls.
- D-22 (LOW, new): long-context price multipliers not modeled in
  budget estimates (transcripts are capped at 60k chars, far below the
  272K threshold, so exposure is bounded).

## 11. Readiness gates

### Gate A — Local operational readiness: **PASS**

Application launches; dependencies resolve; all five CLI commands
executed and verified (run / status / report / resume / cancel);
67 tests pass; state transitions, persistence, cancellation, and
budget guards operate as tested.

### Gate B — Live integration readiness: **BLOCKED_BY_CREDENTIALS**

Real model API requests, real search requests, structured-output
validation against the live API, and a genuine research report all
require credentials that are unavailable. (Spending authorization is
also pending; credentials are the first blocker.)

### Gate C — Production research reliability: **INSUFFICIENT_EVIDENCE**

Adversarial tests pass, audit rejection and correction loops work,
crash recovery works, no critical/high defects remain — but a genuine
end-to-end project has not completed, so reliability of live research
quality is unproven.

## 12. Overall readiness verdict

## **BLOCKED**

Everything that can be done without credentials and without spending
authorization is done and passing. The single blocking action is the
user's: provide an `OPENAI_API_KEY` (and, recommended, `TAVILY_API_KEY`)
and approve a total validation spending ceiling. Proposed ceiling:
**$30** (up to 3 live attempts at the $10 per-project cap). On approval,
execution resumes at the live-validation step with the exact commands in
`LIVE_TEST_RESULTS.md`; no further engineering is needed first.

## 13. Exact commands for future projects

```bash
cd ~/workspace/autonomous-research
source .venv/bin/activate
export OPENAI_API_KEY="..." TAVILY_API_KEY="..."   # from your own vault
python main.py run "Research objective"
python main.py status <PROJECT_ID>
python main.py report <PROJECT_ID>
python main.py resume <PROJECT_ID>
python main.py cancel <PROJECT_ID>
.venv/bin/python -m pytest tests/ -q
```

## 14. Deliverables

- `PRODUCTION_AUDIT.md` (updated with Phase 3 addendum)
- `DEFECT_REGISTER.md` (updated: D-16–D-22)
- `LIVE_TEST_RESULTS.md` (updated: Phase 3 attempt + ceiling proposal)
- `REMEDIATION_LOG.md` (updated: R-11–R-19)
- `DEPLOYMENT_GUIDE.md` (new)
- `FINAL_ACCEPTANCE_REPORT.md` (this file)

---

# Phase 4 Addendum (October 28, 2026) — Live Deployment Attempt

## Baseline re-verification

Phase 3's reported state reproduced exactly before any Phase 4 change:
**67 passed, 1 skipped** (6.14 s). Phase 4 work added 5 tests
(`test_phase4.py`); final suite: **72 passed, 1 skipped** (5.81 s).

## What Phase 4 implemented (authorized preparation, $0 spent)

- **`.env` loading** (`src/config.py::load_dotenv`, called by `main.py`):
  repo `.env` is now a supported configuration mechanism; real
  environment variables take precedence; values are never printed or
  logged. `.env.example` extended with placeholders for all current
  settings. `.gitignore` continues to exclude `.env`.
- **Cumulative validation ledger** (`src/storage/ledger.py`,
  `projects/validation_ledger.json`): every paid call's estimated cost
  (LLM, search, retries, failed executions) is recorded persistently;
  failures, restarts, and resumes cannot reset it. Engine preflight now
  enforces BOTH caps: per-project ($10) and cumulative ($30,
  `AR_TOTAL_VALIDATION_BUDGET`); the cumulative check applies even to a
  new project's first call. New CLI command `python main.py ledger`.
- **Live smoke script** (`scripts/smoke_live.py`): minimal OpenAI
  (auth + model + strict structured output + usage) and Tavily (auth +
  parsing) checks, spending recorded in the ledger, JSON summary with
  credential statuses, exit codes 0/2/3. No mock responses are used as
  live evidence.

## Credential validation result: CREDENTIAL_MISSING

Checked (presence only, no values read, printed, or stored):
environment variables absent; repo `.env` absent; `~/.env`,
`~/workspace/.env`, `~/.config/autonomous-research/.env` absent.
Smoke script output: `{"status": "CREDENTIAL_MISSING",
"openai_key_present": false, "tavily_key_present": false}`,
exit code 2, ledger $0.00. No live connectivity test, live research
project, or generalization test was executed, and no paid call was made.

## Acceptance gates G1–G17 (Phase 4)

| Gate | Requirement | Verdict |
|---|---|---|
| G1 | Repository launches | PASS |
| G2 | Automated tests pass | PASS (72 passed, 1 skipped) |
| G3 | OpenAI live connectivity verified | BLOCKED (no credentials) |
| G4 | Search-provider live connectivity verified | BLOCKED (no credentials) |
| G5 | Structured outputs function | PASS (offline: strict-schema tests + provider fallback tests; live confirmation pending) |
| G6 | Four-agent workflow completes | PASS (offline, stub-driven; live pending) |
| G7 | Genuine external research performed | BLOCKED (no credentials) |
| G8 | Material claims independently checked | PASS (offline adversarial suite; live pending) |
| G9 | Auditor can reject unsupported findings | PASS (offline) |
| G10 | Correction loops function | PASS (offline) |
| G11 | Reports and evidence persist | PASS |
| G12 | Resume and cancellation work | PASS |
| G13 | Spending controls operate | PASS (offline: project + cumulative preflight, ledger, runtime limit) |
| G14 | No unresolved critical/high defects | PASS |
| G15 | CLI works end to end | PASS (all commands incl. `ledger` executed) |
| G16 | Generalization test or budget blocker documented | BLOCKED (credential blocker documented here; budget authorized but unusable without keys) |
| G17 | Total validation spending within authorization | PASS ($0.00 of $30.00; no paid calls made) |

## Three verdicts (Phase 4)

- **A. Local operational readiness: PASS**
- **B. Live integration readiness: BLOCKED_BY_CREDENTIALS**
- **C. Production research reliability: INSUFFICIENT_EVIDENCE**

## Overall status: **BLOCKED**

No genuine live research report exists yet; stub demo reports in
`projects/` are explicitly canned output and must not be presented as
research. All authorized preparation is complete. Resumption requires
exactly one user action (see handoff message).

## Resumption commands (once credentials are configured)

```bash
cd ~/workspace/autonomous-research
source .venv/bin/activate
python scripts/smoke_live.py   # expect OK, ledger shows smoke cost only
python main.py run "Identify and evaluate three realistic, legally permissible, AI-assisted commodity arbitrage businesses that can be started with less than \$2,000 in initial capital. For each opportunity, investigate sourcing, resale channels, purchase prices, sale prices, transaction fees, shipping, taxes where applicable, inventory losses, competition, liquidity, operational complexity, automation potential, and legal or platform restrictions. Distinguish actual executable opportunities from hypothetical price differences. Determine whether the available evidence supports positive net profit after relevant costs. Reject opportunities lacking sufficient evidence. Rank remaining opportunities by risk-adjusted attractiveness and suitability for automation. If fewer than three viable opportunities are supported, report fewer than three. Do not make purchases or execute transactions."
python main.py ledger           # cumulative spend vs. $30 cap
```
