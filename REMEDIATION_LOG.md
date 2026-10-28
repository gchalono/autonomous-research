# Remediation Log — Phase 2 Audit

Every fix below was implemented in code and covered by a test. Test
command for the whole suite (run from the repository root, venv active):

```bash
.venv/bin/python -m pytest tests/ -q
# Result at end of audit: 45 passed, 1 skipped (live-API test, by design)
```

## R-01 — Strict-mode schema compliance (defect D-01, CRITICAL)

- **File:** `src/llm/provider.py` — new `make_strict_schema()`.
- **Change:** recursively sets `additionalProperties: false`, completes
  `required` with every property, strips `default` keywords, and inlines
  `$ref`/`$defs` (including Pydantic's `{"$ref", "default"}` sibling
  form, found by a failing test during remediation).
- **Fallback:** on a schema-related provider rejection, one retry with
  `{"type": "json_object"}`; Pydantic validation + repair retry still
  enforces the contract.
- **Tests:** `test_strict_schema_has_no_strict_violations` (all six
  contracts), `test_openai_provider_falls_back_on_schema_rejection`
  (fake client rejecting strict, accepting JSON mode).

## R-02 — Deprecated default models (defect D-02, HIGH)

- **Files:** `src/config.py`, `.env.example`.
- **Change:** defaults `gpt-5`/`gpt-5-mini` → `gpt-5.4-mini`
  (creator/evaluator), `gpt-5.6-terra` (executor/auditor), after
  confirming `gpt-5` family deprecation (shutdown announced Dec 11,
  2026) on OpenAI's model list. Prices for new defaults marked as
  placeholder estimates in code comments.
- **Tests:** existing suite passes unchanged (models are configuration;
  stub tests are model-agnostic). No test can verify live model
  availability without credentials — noted as a pre-production check.

## R-03 — Deterministic claim-to-evidence analysis (defect D-03, HIGH)

- **File:** `src/orchestration/claim_check.py` (new).
- **Change:** `analyze_claim_support()` enforces VERIFIED-needs-CONFIRMED,
  cited-id existence, evidence for derivations, non-empty passages,
  executor fetch-history provenance, and tool-failure/limitation
  consistency. Wired into `_step_audit`; code issues join the correction
  task alongside auditor issues.
- **Tests:** `test_verified_claim_with_unreachable_source_cannot_approve`,
  `test_claim_citing_nonexistent_source_is_major_and_blocks`,
  `test_claim_analyzer_unit_cases`,
  `test_passage_presence_alone_does_not_support_claim`.

## R-04 — Verification facts persisted; audit lists from code (defect D-04, HIGH)

- **File:** `src/orchestration/engine.py` (`_step_audit`).
- **Change:** verified report re-saved to store and artifacts after
  verification; `audit.verified_sources`/`unverified_sources` overwritten
  from code re-fetch results before saving.
- **Test:** `test_verification_facts_persisted_not_llm_asserted`
  (lying-auditor stub fabricating `S999`; saved report shows `S1`
  CONFIRMED in the final report).

## R-05 — APPROVE downgrade extended to MAJOR issues (defect D-03 follow-up)

- **File:** `src/orchestration/engine.py` (`_step_audit`).
- **Change:** downgrade condition widened from CRITICAL-only to
  CRITICAL-or-MAJOR open issues, per spec §9.4 (major defects must be
  corrected or explicitly justified; only minor issues may remain).
- **Test:** `test_claim_citing_nonexistent_source_is_major_and_blocks`
  (MAJOR dangling citation + APPROVE → `COMPLETED_WITH_LIMITATIONS`).

## R-06 — Full re-execution wired (defect D-05, MEDIUM)

- **Files:** `src/orchestration/engine.py` (`_step_correct`,
  `_run_execution`), `src/agents/executor.py` (`full_reexecution` flag).
- **Change:** correction step loads the last audit, applies
  `needs_full_reexecution`, and on trigger restarts research without the
  previous report, with a FULL RE-EXECUTION transcript note.
- **Test:** `test_full_reexecution_wiring` (methodology-invalid audit →
  correction transcript contains the marker; run completes).

## R-07 — Draft revision normalization (defect D-06, MEDIUM)

- **File:** `src/orchestration/engine.py` (`_step_draft`).
- **Change:** engine forces `revision_number = version` and re-saves the
  normalized spec, so version keys cannot desynchronize.
- **Tests:** existing revision tests continue to pass.

## R-08 — CLI unknown-project handling (defect D-07, LOW)

- **File:** `main.py`.
- **Change:** `KeyError` caught around status/resume/report/cancel;
  clean `error: unknown project ...` + exit 2, no traceback.
- **Test:** `test_cli_unknown_project_clean_error`.

## R-09 — Executor transcript cost bound (defect D-08, MEDIUM)

- **File:** `src/agents/executor.py`.
- **Change:** message capped at 60k chars; oldest tool-result blocks
  dropped first, spec header always kept, truncation marker inserted.
  (An initial implementation with fixed indices was wrong for
  variable-length headers and was rewritten with a separate blocks list
  before the suite went green.)
- **Test:** `test_executor_transcript_is_bounded` (30k-char tool outputs
  over 6 turns; observed message lengths stay bounded).

## R-10 — Auditor contradiction duty (defect D-09, LOW)

- **File:** `src/agents/auditor.py` (system prompt).
- **Change:** contradictions must be named explicitly; passage presence
  stated as necessary, never sufficient.
- **Test:** covered indirectly by
  `test_passage_presence_alone_does_not_support_claim`.

## Not remediated (open, with reasons)

- **D-10 semantic entailment:** no deterministic solution exists
  without another model judgement; mitigated by structural enforcement +
  dedicated auditor + correction loop. Supervise early live reports.
- **D-11 live validation:** impossible without credentials; exact
  commands recorded in `LIVE_TEST_RESULTS.md`.
- **D-12 prices, D-13 mid-call cancellation, D-14 keyless search,
  D-15 exact-once:** documented limitations; fixes would require
  provider data, async cancellation machinery, a paid search key, or a
  distributed-transaction design respectively — all out of proportion to
  their impact for a CLI research tool with read-only tools.

---

# Phase 3 remediation (October 28, 2026)

Final suite after all items: **67 passed, 1 skipped** (live test).

## R-11 — Preflight budget estimation (defect D-16)

- **Files:** `src/agents/common.py`, `src/orchestration/engine.py`,
  `src/config.py`, agent entry points.
- **Change:** `call_agent` estimates input tokens (text length / 4) and
  passes them with `AR_ESTIMATED_OUTPUT_TOKENS` (default 1500) to the
  engine's cost callback in `preflight=True` mode, which refuses the
  call when spent + estimate exceeds budget. Preflight never records
  spend; the first call of a project is exempt so tiny budgets cannot
  deadlock a run. Threaded through creator, evaluator, executor, and
  auditor entry points from `settings.estimated_output_tokens`.
- **Tests:** `test_preflight_blocks_call_that_would_breach_budget`,
  `test_preflight_does_not_record_spend`.

## R-12 — Runtime limit (defect D-17)

- **Files:** `src/orchestration/engine.py`, `src/config.py`.
- **Change:** `_check_runtime` compares wall-clock elapsed time against
  `AR_MAX_RUNTIME_S` (default 3600) before each phase; on breach it
  fails the run with an explicit reason and preserved artifacts.
- **Tests:** `test_runtime_limit_fails_run_with_reason` (also covers
  `FAILED_EXECUTION` terminal label).

## R-13 — Transient-error recovery (defect D-18)

- **Files:** `src/agents/common.py`, `src/orchestration/engine.py`.
- **Change:** transient markers (timeout, rate limit, 429/502/503,
  overload) are no longer wrapped as agent-output failures; the engine
  catches raw `LLMError`, logs it, leaves the project non-terminal, and
  returns `transient_error` so a later `resume` continues. Permanent
  errors still fail. Found during this fix: the state machine allows
  FAILED edges only under event `"failed"` from CREATED, so the runtime
  check uses that event name.
- **Tests:** `test_transient_error_keeps_project_resumable`,
  `test_non_transient_llm_error_still_fails`.

## R-14 — Model fallback with recorded actual model (Phase 2 §6.3)

- **Files:** `src/llm/provider.py`, `main.py`, `src/orchestration/engine.py`.
- **Change:** `OpenAIProvider` accepts `fallback_model` (from
  `AR_MODEL_FALLBACK`); on a model-not-found error it retries once with
  the fallback, records `models_used` and `last_response_id`, and the
  engine persists `models_used` + `configured_models` in
  `run_metadata.json`. No unconfigured substitution is possible.
- **Tests:** `test_model_fallback_used_and_recorded`.

## R-15 — Observability: run log, terminal labels, notification

- **Files:** `src/storage/artifacts.py`, `src/orchestration/engine.py`,
  `main.py`.
- **Change:** `run_log.jsonl` per project (transitions, LLM calls with
  tokens/estimated cost/response id, search calls, transient errors;
  no prompts or secrets); `terminal_status` mapping (§15.1) in `status`
  and metadata; `DONE:` completion banner plus `AR_NOTIFY_CMD` hook
  (no shell) on `run`.
- **Tests:** `test_run_log_written_without_secrets`,
  `test_terminal_status_mapping`.

## R-16 — Claim outcomes + verification appendix (spec §9)

- **Files:** `src/models/contracts.py`, `src/orchestration/claim_check.py`,
  `src/orchestration/engine.py`.
- **Change:** `ClaimClassification` gains `PARTIALLY_SUPPORTED`,
  `UNSUPPORTED`, `CONTRADICTED`, `UNVERIFIABLE` with documented
  semantics; analyzer rules extended (PARTIALLY_SUPPORTED like
  INFERRED; CONTRADICTED needs contradicting evidence; UNSUPPORTED
  without sources is MINOR, not blocking, so honest rejections are not
  punished); final reports gain §10 claim-verification detail.
- **Tests:** `test_new_claim_outcomes_analyzer_rules`,
  `test_final_report_claim_verification_appendix`.

## R-17 — Limitations-path final report (defect D-19)

- **Files:** `src/orchestration/engine.py`.
- **Change:** `_step_audit` renders and writes `final_report.md` before
  transitioning to `COMPLETED_WITH_LIMITATIONS`.
- **Tests:** `test_case9_inaccessible_webpage` (asserts UNREACHABLE in
  the final report).

## R-18 — Prices corrected, .gitignore (defects D-20, D-21)

- **Files:** `src/config.py`, `.gitignore`.
- **Change:** verified prices applied (see D-20); `.gitignore` excludes
  `.env`, `.venv/`, `projects/`, caches.

## R-19 — Adversarial-2 and hardening suites

- **Files:** `tests/test_adversarial2.py` (9 tests),
  `tests/test_hardening.py` (13 tests).
- **Change:** 15-case adversarial mapping (see
  `FINAL_ACCEPTANCE_REPORT.md` §7) plus cancellation no-op,
  budget-exhaustion no-op, and search-cost tracking (recorded when
  `AR_TAVILY_COST_PER_SEARCH` > 0, otherwise counted only).
- **Tests:** all pass in the final 67-test run.

---

# Phase 4 remediation (October 28, 2026)

Final suite: **72 passed, 1 skipped** (live test). Validation spending:
**$0.00** (no credentials, no paid calls).

## R-20 — `.env` loading (Phase 4 §4)

- **Files:** `src/config.py` (`load_dotenv`), `main.py`, `.env.example`.
- **Change:** repo `.env` is now loaded automatically (no overwrite of
  real environment variables); only `KEY=VALUE` lines with optional
  `export` prefix and quotes are parsed; values are never printed or
  logged. `.env.example` extended with placeholders for all current
  settings including the cumulative budget and fallback model.
- **Tests:** `test_dotenv_loading_no_overwrite` (file values load,
  real env wins, missing file is not an error).

## R-21 — Cumulative validation ledger (Phase 4 §5)

- **Files:** `src/storage/ledger.py` (new), `src/orchestration/engine.py`,
  `src/config.py`, `main.py`.
- **Change:** persistent JSON ledger at
  `<projects_root>/validation_ledger.json` records every paid call's
  estimated cost with provider/model/kind/timestamp; a new instance
  over the same file sees the same total, so failures, restarts, and
  resumes cannot reset it. Engine preflight enforces the cumulative cap
  (`AR_TOTAL_VALIDATION_BUDGET`, default $30) in addition to the
  per-project cap, including for a new project's first call.
  `python main.py ledger` reports cap/spent/remaining.
- **Tests:** `test_ledger_records_and_persists`,
  `test_cumulative_cap_blocks_new_project_first_call`,
  `test_engine_calls_land_in_ledger`, `test_ledger_cli`.

## R-22 — Live smoke script (Phase 4 §7)

- **Files:** `scripts/smoke_live.py` (new).
- **Change:** minimal live checks (OpenAI auth + model + strict output
  + usage; Tavily auth + parsing) with JSON summary, credential-status
  classification, exit codes 0/2/3, and ledger accounting for the
  smoke spend. Verified in the no-credential case: exits 2 with
  `CREDENTIAL_MISSING` and $0 recorded.
- **Tests:** exercised manually (exit 2 path); the live path is
  exercised by the script itself once credentials exist and is not
  faked with mocks.

---

# Urgent live fix (October 28, 2026)

Final suite after fix: **79 passed, 1 skipped** (live test).

## R-23 — JSON-object fallback 400 (defect D-27, HIGH)

- **Files:** `src/llm/provider.py`, `tests/test_json_fallback.py` (new).
- **Root cause:** `OpenAIProvider.complete` tried strict mode first and
  fell back to `{"type": "json_object"}` on schema rejection, but sent
  the user message unchanged. The Responses API rejects `json_object`
  requests whose INPUT messages lack the word "json" (HTTP 400). Agent
  SYSTEM prompts contain "JSON" but agent user messages do not, so the
  fallback always 400'd for agents whose user text lacked the word.
- **Change (minimal, no unrelated functionality):** in the candidate /
  format loop, `json_object` requests get `JSON_MODE_SUFFIX` appended
  to the input ("Return your response as valid json only, matching the
  requested schema."); strict requests are byte-identical to before.
  The strict rejection is now preserved in error messages on both the
  immediate-raise and exhausted paths, so a future strict failure is
  diagnosable instead of masked by the fallback's error.
- **Validation preserved:** fallback responses still go through
  Pydantic validation + one repair retry in `agents/common.py`
  (test: invalid enum via fallback → `AgentOutputError` after two
  failed validations).
- **Tests:** 7 new regression tests, including a fake client enforcing
  the real API rule (old request shape reproduces the exact reported
  400; fixed shape succeeds), strict-success without suffix, malformed
  JSON, and non-schema API error propagation (401, single attempt).
- **Not claimed:** no live test was executed in this environment (no
  credentials here). The fix is proven against the enforced API rule
  in tests; the user's next live run is the live confirmation. The
  failed project `17833c7a8172` is terminal (FAILED) and cannot be
  resumed; a new `run` is required, and its $0.0053 remains recorded
  spend, not lost.

---

## R-24 — Native executor tool-calling protocol (defect D-28, HIGH)

- **Files:** `src/llm/provider.py`, `src/agents/executor.py`,
  `src/agents/common.py`, `src/models/contracts.py`,
  `src/orchestration/engine.py`, `tests/test_tool_protocol.py` (new).
- **Root cause (three layers):** (1) The executor protocol was textual:
  the model had to emit a JSON envelope, and the only enforcement was
  strict mode; the json_object fallback enforces validity, not schema,
  so the model emitted bare tool objects in two different formats and
  concatenated them. (2) `call_agent` repaired only validation
  failures; a non-JSON payload raises before validation, so the run
  died on the first malformed turn with no repair attempt. (3) The
  recorded "0 tool calls" was a symptom, not a dispatch failure: the
  malformed text never reached the tool runner.
- **Change (executor only; creator/evaluator/auditor untouched):**
  `OpenAIProvider.create_tool_response` implements native function
  calling with the same fallback discipline as `complete()` (strict
  tool definitions, then non-strict on schema rejection, then fallback
  model on model-not-found; strict errors preserved). The executor
  builds function definitions from Pydantic argument models
  (`WebSearchArgs`, `FetchPageArgs`, `CalculateArgs` in contracts.py)
  plus a `submit_report` function carrying the full ExecutionReport
  schema. The native loop's states are explicit: function calls mean
  continue, a valid `submit_report` means done, prose means a protocol
  reminder (bounded by `max_iterations`). Unknown tools, unparseable
  arguments, and arguments failing validation become error outputs
  fed back to the model -- never executions. Tool outputs are
  injection-scanned and wrapped exactly as in the legacy loop, and the
  transcript is capped by dropping whole call/output rounds (no
  orphaned outputs). The engine passes the client as `tool_client`
  only when `supports_native_tools` is true; stubs keep the legacy
  loop, which now also repairs one non-JSON response.
- **Dispatch accounting:** model-generated requests, validated calls,
  executed calls, and failed calls are distinct by construction --
  only validated actions reach the runner, and the runner records
  every execution (success or failure) in the store, so the project
  status can never report zero tool calls after a validated tool ran.
- **Tests:** 15 new tests in `tests/test_tool_protocol.py`: exact
  concatenated-JSON rejection (never split/parsed), legacy one-repair
  success and bounded repair failure, valid search reaching the
  adapter with results consumed by the next turn, malformed arguments
  never executing, unknown tool never executing, multiple sequential
  calls, empty results, provider failure as data, prose-only turn,
  bounded invalid final report, native budget exhaustion, native
  strict-rejection and model-not-found fallbacks, and a mocked
  end-to-end engine run (search -> dispatch -> consumption ->
  schema-valid report -> COMPLETED_APPROVED with tool_calls >= 1).
  Full suite after fix: **94 passed, 1 skipped** (live test).
- **Not claimed:** no live test was executed in this environment (no
  credentials here). The user's next live `run` is the live
  confirmation; project `c9b4973708ec` is terminal FAILED and needs a
  new run. Which agent step's strict call was rejected in either live
  failure is still undiagnosed remotely; strict errors are now
  preserved in failure messages for that diagnosis.
