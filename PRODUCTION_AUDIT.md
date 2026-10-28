> Historical record of earlier revisions. Current findings, fixes and limitations
> are in [ENGINEERING_AUDIT.md](ENGINEERING_AUDIT.md); current bounded live
> instructions are in [LIVE_VALIDATION.md](LIVE_VALIDATION.md). Earlier readiness
> claims do not establish live validation of the current implementation.

# Production Readiness Audit — Phase 2

**System audited:** `~/workspace/autonomous-research/` (autonomous four-agent
research system, Phase 1 implementation)
**Audit date:** October 28, 2026
**Method:** full code inspection of every module, SDK introspection
(openai 3.40.0), documentation checks against OpenAI's published model
list and structured-output rules, execution of the complete test suite,
and targeted reproduction of suspected defects with stub providers.
No live API calls were made: no `OPENAI_API_KEY` or `TAVILY_API_KEY` was
present in the environment and no `.env` file existed (presence checked
only; no secret values were read, printed, or stored).

## Verdict

## **CONDITIONALLY READY**

Conditions for production use (all must hold before real research runs):

1. Set a valid `OPENAI_API_KEY` and run the live end-to-end test
   (`LIVE_TEST_RESULTS.md` gives the exact commands) until it passes.
2. Set `TAVILY_API_KEY` for reliable search; keyless DuckDuckGo scraping
   is unreliable (verified: both DDG endpoints return bot-guard pages
   from ordinary networks).
3. Re-verify model ids and prices against OpenAI's current pages at
   deploy time; the previous defaults were already deprecated once.
4. Treat the first few live reports as supervised: read the audit
   findings and the final report's limitations section before acting on
   conclusions.

`PRODUCTION READY` is not awarded: the rules of this audit forbid it
without a successful live end-to-end test, and none was possible here.

## 1. Agent independence and structured communication — PASS (with fixes)

All four agents communicate through validated Pydantic contracts
(`src/models/contracts.py`); the orchestrator never parses narrative
Markdown for decisions. Agent calls go through `agents/common.py`, which
validates output and allows exactly one repair retry before failing the
run safely. Independence is real in structure: the auditor receives the
objective, approved prompt, report, source register, and code-level
verification facts — not the executor's interpretation alone.

Defect found and fixed: the OpenAI provider sent raw Pydantic schemas
with `strict: true`, which strict mode rejects (400) because fields with
defaults were missing from `required` and no object set
`additionalProperties: false`. Reproduced by schema inspection across all
six contracts. Fixed with `make_strict_schema` (required-completion,
additionalProperties, default-stripping, `$ref` inlining) plus a
once-only fallback to plain JSON mode when the provider rejects a strict
schema. Pydantic validation + repair retry still enforces the contract
in the fallback path.

## 2. Orchestrator: revisions, corrections, termination, persistence — PASS

State machine (`states.py`) permits exactly the specified transitions;
invalid transitions raise. Revision cap (3) and correction cap (2) are
enforced in code and tested, including limit-exhaustion paths:
prompt-limit → `FAILED` with an explicit reason; correction-limit →
`COMPLETED_WITH_LIMITATIONS`, never clean `COMPLETED`. Budget is checked
before every LLM call (pre-call gate added in Phase 1, kept) and
exhaustion preserves intermediate artifacts. Resume reuses stored step
outputs, proven by tests asserting zero duplicate LLM calls after resume
from prompt-review and execution checkpoints. Cancellation is honored
between phases.

Defects found and fixed: (a) full re-execution (`needs_full_reexecution`)
existed but was never called — now wired into the correction step;
(b) prompt-draft revision numbers were taken from the LLM instead of the
engine — now normalized and re-saved; (c) CLI crashed with a traceback
on unknown project ids — now a clean error and exit code 2.

## 3. Citation verification — STRENGTHENED, with a stated residual limit

Phase 1 verified passage *presence* on re-fetched pages. That is
necessary but not sufficient: a present passage does not entail the claim
citing it, and a `VERIFIED` claim citing an unreachable source could
previously pass if the auditor LLM missed it.

Fixes applied:

- New deterministic analyzer (`src/orchestration/claim_check.py`) enforces
  in code: `VERIFIED` requires at least one independently CONFIRMED
  source; cited ids must exist in the register; INFERRED/ESTIMATED claims
  need cited evidence; sources need passages; citations must appear in
  the executor's own fetch history; tool failures with no recorded
  limitation are flagged.
- The orchestrator downgrades `APPROVE` to `CORRECTIONS_REQUIRED` when
  any open CRITICAL **or MAJOR** issue exists (Phase 1 covered CRITICAL
  only; spec §9.4 requires the same for MAJOR).
- Verification statuses are now written back to the stored report and
  artifacts, so the final report shows CONFIRMED/UNREACHABLE instead of
  the executor's original UNCHECKED values (previously lost).
- Audit `verified_sources`/`unverified_sources` now come from code
  re-fetching, not from LLM assertions (a stub test proved the LLM
  could previously fabricate them).
- Auditor prompt now requires contradictions to be named explicitly and
  states that passage presence is necessary, never sufficient.

**Residual limit (honest):** semantic entailment — whether a real
passage's meaning actually supports its claim — still rests on the
auditor LLM's judgement. No deterministic check can settle that without
another model judgement. The system now guarantees the structural
preconditions and forces the semantic question to a dedicated auditor;
it does not claim to have solved semantic verification.

## 4. Substantive multi-source research — MECHANICALLY CAPABLE, UNPROVEN LIVE

The executor tool loop (search → fetch → calculate, bounded iterations,
capped transcript) plus the source register and verification pipeline can
support genuine multi-source research. This was verified mechanically
with stub providers and fake tools, and the search/fetch tools were
exercised against real HTTP (Tavily path via mocked HTTP; DuckDuckGo
path verified to fail honestly rather than fabricate when bot-guarded).
Substantive quality of live research — source diversity, depth,
calculation correctness — cannot be established without a live run and
is therefore NOT claimed.

## 5. Failure handling — PASS

Tested and observed: failed searches return errors the executor must
record as limitations (and the analyzer flags reports that hide tool
failures); inaccessible sources become UNREACHABLE and downgrade any
VERIFIED claim resting on them; contradictory evidence is now an
explicit auditor duty; unresolved critical findings after the correction
limit produce `COMPLETED_WITH_LIMITATIONS` with the issues listed, never
silent success.

## 6. OpenAI SDK integration — PASS after fixes

- SDK 3.40.0: `client.responses.create` accepts `instructions`, `input`,
  `text.format`; `response.output_text` and `usage.input_tokens` /
  `usage.output_tokens` confirmed by introspection.
- Structured outputs: strict-mode schema rules confirmed against
  published documentation; provider now emits compliant schemas with a
  documented fallback.
- Error handling: API failures surface as `LLMError` → run fails safely
  with artifacts preserved; schema rejections trigger the JSON fallback.
- **Model compatibility — defect fixed:** configured defaults
  (`gpt-5`, `gpt-5-mini`) are listed as Deprecated on OpenAI's own
  model page, with shutdown announced for December 11, 2026. Defaults
  changed to `gpt-5.4-mini` (creator/evaluator) and `gpt-5.6-terra`
  (executor/auditor). Prices for the new defaults are placeholder
  estimates and must be verified; budget math is estimation only.
- Tool configuration: the system does not use OpenAI function calling;
  the executor's tool loop is orchestrator-driven (the model requests
  tool calls in structured JSON, code executes them). This is a
  deliberate design choice, documented in code.

## 7. Test adequacy — IMPROVED

Phase 1's 35 tests confirmed expected behavior. Phase 2 added 10
adversarial tests (total 45 passing, 1 skipped) targeting defects found
by inspection: strict-schema validity for every contract, provider
schema fallback, VERIFIED-without-confirmed-source, dangling citations,
fabricated audit source lists, full-re-execution wiring, transcript cost
bounding, CLI error handling, and the passage-presence limit. The live
end-to-end test remains skipped without credentials — by design, not by
omission.

## 8. Budget feasibility — NOT ESTABLISHED

The $10/project target is enforced mechanically (pre-call gate, token
tracking, transcript cap, bounded iterations). Whether a genuine
research assignment completes within $10 depends on live model prices,
prompt sizes, and tool-loop length, none of which can be measured
without API access. The transcript cap (60k chars) bounds the largest
cost driver. Do not promise $10 completion until the live test measures
real spend.

## Remaining limitations (carried forward)

- No live validation (no credentials in this environment).
- Semantic claim support rests on the auditor LLM.
- Cancellation is honored between phases, not mid-LLM-call.
- Budget figures are estimates; the provider's bill governs.
- Keyless search is unreliable; Tavily key recommended.
- Exact-once execution is not claimed for external API calls.

---

# Phase 3 Addendum (October 28, 2026) — Production Hardening

Phase 2's `CONDITIONALLY READY` claims were independently re-verified
before any Phase 3 change: the 45-test baseline reproduced green, and
the strict-schema fix, claim analyzer, verification persistence, and
full-re-execution wiring were all confirmed present in code and covered
by tests.

Phase 3 hardening (all implemented, tested, and documented in
`REMEDIATION_LOG.md` R-11–R-19):

- Preflight budget estimation before every LLM call (first call never
  blocked, so tiny budgets cannot deadlock a run).
- Wall-clock runtime limit (`AR_MAX_RUNTIME_S`, default 3600 s).
- Transient-error recovery: rate limit / timeout leaves a project
  resumable instead of failing it permanently.
- Model fallback (`AR_MODEL_FALLBACK`) with the actually-used model
  recorded in `run_metadata.json`.
- Structured JSONL run log, terminal-status labels (§15.1), completion
  banner + `AR_NOTIFY_CMD` hook, search-cost tracking.
- Extended claim outcomes (`PARTIALLY_SUPPORTED`, `UNSUPPORTED`,
  `CONTRADICTED`, `UNVERIFIABLE`) and a per-claim verification appendix
  in final reports.
- Final report now written on the `COMPLETED_WITH_LIMITATIONS` path
  (previously missing).
- Model prices corrected to freshly verified values (gpt-5.4-mini
  $0.75/$4.50, gpt-5.6-terra $2.00/$12.00); `.gitignore` added.
- 15-case adversarial validation and recovery testing: all pass on
  observed state transitions and artifacts.

Final suite: **67 passed, 1 skipped** (live test, by design).

This audit's verdict is superseded by `FINAL_ACCEPTANCE_REPORT.md`:
Gate A PASS, Gate B BLOCKED_BY_CREDENTIALS, Gate C
INSUFFICIENT_EVIDENCE, overall **BLOCKED** — pending user-provided API
credentials and approval of a $30 total validation spending ceiling.

---

# Phase 4 Addendum (October 28, 2026) — Live Deployment Attempt

Baseline re-verified (67 passed, 1 skipped) before Phase 4 changes;
final suite **72 passed, 1 skipped**. New: `.env` loading
(`src/config.py::load_dotenv`), cumulative validation ledger with
dual-cap preflight (`src/storage/ledger.py`, `python main.py ledger`),
and a minimal live smoke script (`scripts/smoke_live.py`).

Credential validation: **CREDENTIAL_MISSING** — no keys in environment,
repo `.env`, `~/.env`, `~/workspace/.env`, or
`~/.config/autonomous-research/.env`. Smoke test exited 2 with $0.00
spent. Spending authorization ($30 total, $10/project, max 3 attempts)
is recorded but unusable without credentials.

Current standing: Gate A PASS, Gate B BLOCKED_BY_CREDENTIALS, Gate C
INSUFFICIENT_EVIDENCE; overall **BLOCKED**. Full gate table (G1–G17),
verdicts, and resumption commands are in
`FINAL_ACCEPTANCE_REPORT.md` (Phase 4 addendum).
