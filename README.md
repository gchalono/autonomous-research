# Autonomous Research System

Current engineering status: [ENGINEERING_AUDIT.md](ENGINEERING_AUDIT.md).
The full native workflow is tested offline; live end-to-end success remains
unverified. See [LIVE_VALIDATION.md](LIVE_VALIDATION.md) for a bounded, explicitly
authorized live run using existing local credentials.

A deterministic four-agent research application. One command replaces a
manual workflow across four separate ChatGPT conversations:

1. **Prompt Creator** turns your objective into a rigorous execution prompt.
2. **Prompt Evaluator** independently reviews it and demands revisions.
3. **Research Executor** executes the approved prompt with real tools.
4. **Independent Execution Auditor** verifies the work, re-fetching sources
   in code, and demands corrections.

The **orchestrator is ordinary deterministic software**: it owns state
transitions, revision/correction caps, spending limits, cancellation and
persistence. LLMs supply content only — they never decide a transition, a
limit, or whether a defect is resolved.

## Quick start (macOS)

```bash
cd autonomous-research
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # or: pip install pydantic openai pytest
cp .env.example .env                   # then add your OPENAI_API_KEY
```

Run a project:

```bash
python main.py run "Research autonomous commodity arbitrage businesses with less than $2,000 in capital"
python main.py status <PROJECT_ID>
python main.py resume <PROJECT_ID>
python main.py report <PROJECT_ID>
python main.py cancel <PROJECT_ID>
```

With `OPENAI_API_KEY` set, research uses the OpenAI Responses API with
JSON-schema structured outputs. Without it, the CLI runs the deterministic
stub provider and says so loudly: the workflow completes end to end, but
report content is canned demo output, **not** genuine research.

For reliable web search, set `TAVILY_API_KEY` (free tier available at
tavily.com). Without it the tool falls back to keyless DuckDuckGo HTML
scraping, which is brittle — many networks return a bot-guard page with no
results, in which case the tool reports the failure honestly and the
executor records the limitation instead of inventing sources.

## How it works

```
CREATED → PROMPT_DRAFTING → PROMPT_REVIEW ⇄ PROMPT_REVISION
            (approve) ↓                      (max 3 revisions)
          EXECUTING → EXECUTION_AUDIT ⇄ EXECUTION_CORRECTION
            (approve) ↓                      (max 2 corrections)
          FINALIZING → COMPLETED
```

Other terminal states: `COMPLETED_WITH_LIMITATIONS` (correction limit
reached with major/critical issues still open — never reported as clean
success), `FAILED`, `CANCELLED`, `BUDGET_EXHAUSTED` (default budget
$10/project, configurable via `AR_BUDGET_USD`).

Every state change is timestamped, persisted to SQLite
(`projects/research.db`) and logged as an event row. Agent outputs are
stored per step, so `resume` never repeats a completed LLM call or
duplicates an artifact. Final reports are written atomically (temp file +
rename), so a crash can never expose a half-written report as complete.

Each project directory contains: `objective.md`, `prompt_vN.md` (every
version preserved), `prompt_evaluation.json`, `approved_prompt.md`,
`execution_report.md`, `sources.json`, `audit_report.json`,
`corrections.md` (when applicable), `final_report.md`, `run_metadata.json`.

## Auditor independence

The auditor is not a summary pass. Before the audit LLM runs, the system
independently re-fetches each cited source (up to `AR_MAX_SOURCES_TO_VERIFY`,
default 8) and checks whether the cited passage actually appears.
Results are `CONFIRMED` / `NOT_FOUND` / `UNREACHABLE` and are handed to the
auditor, which must treat unverified claims as unverified.

**Passage presence is necessary, never sufficient.** A passage existing on
a page does not prove it supports the claim citing it. So a second,
deterministic layer (`src/orchestration/claim_check.py`) enforces the
structural requirements in code, regardless of what the auditor LLM
concludes: a `VERIFIED` claim needs at least one independently CONFIRMED
source; cited source ids must exist in the register; derivations need
cited evidence; sources need passages; citations must come from the
executor's own fetch history. As a third line of defense, the orchestrator
downgrades any `APPROVE` verdict that still lists an open CRITICAL or
MAJOR issue to `CORRECTIONS_REQUIRED`. The semantic question — does this
passage actually entail this claim — remains the auditor LLM's job, and
its prompt says so explicitly, including naming contradictions between
sources rather than resolving them silently. Verification facts written to
the final report come from code re-fetching, never from LLM assertions.

## Security

- Tools are classified `READ_ONLY` / `LOCAL_WRITE` / `EXTERNAL_ACTION` /
  `HIGH_RISK`. External and high-risk tools refuse to run without explicit
  authorization for that exact action. This release ships **no**
  external-action tools: no email, purchases, posts, or account changes.
- Artifact writes are confined to the project workspace (path-escape
  rejected).
- Retrieved web content is untrusted data: it is scanned for common
  instruction-injection patterns, wrapped in delimiters, and labelled as
  data before any LLM sees it. Tool output can never change workflow
  rules, spending limits, or permissions.
- **Generated code execution is disabled by default.** A Python subprocess
  is not a sandbox. Computation uses an AST-validated expression
  evaluator (arithmetic + whitelisted math/statistics only); anything
  else is rejected.
- Secrets come from the environment only; nothing credential-like is
  written to logs or artifacts.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `OPENAI_API_KEY` | — | Enables real LLM research |
| `TAVILY_API_KEY` | — | Reliable search backend |
| `AR_MAX_OUTPUT_TOKENS` | `6000` | Hard per-request output token limit, including reasoning tokens |
| `AR_BUDGET_USD` | `10.0` | Per-project spending target |
| `AR_MODEL_CREATOR` / `AR_MODEL_EVALUATOR` / `AR_MODEL_EXECUTOR` / `AR_MODEL_AUDITOR` | `gpt-5.4-mini` / `gpt-5.4-mini` / `gpt-5.6-terra` / `gpt-5.6-terra` | Model per role (re-verify: `gpt-5` family is deprecated, shutdown announced Dec 11, 2026) |
| `AR_MAX_PROMPT_REVISIONS` | `3` | Prompt revision cap |
| `AR_MAX_CORRECTIONS` | `2` | Correction-cycle cap |
| `AR_MAX_TOOL_ITERATIONS` | `12` | Executor tool-loop bound |
| `AR_PROJECTS_ROOT` | `projects` | Where projects live |

Model names are configuration, not hard-coded logic — but verify them
against OpenAI's current model list before a production run, as model
availability changes.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```

142 tests pass; 1 skipped (the live-API end-to-end test, which only runs
with `AR_RUN_LIVE=1`, both API credentials, an explicit model and prices).

Coverage: everything above, plus the Phase 2 adversarial suite —
strict-mode schema validity for every contract, provider fallback when a
strict schema is rejected, VERIFIED claims without confirmed sources,
dangling citations, verification facts persisted to the final report
instead of LLM assertions, full-re-execution wiring, executor transcript
cost bounding, CLI error handling, and the passage-presence-is-not-support
limit (a confirmed passage that does not support its claim still forces
correction through the auditor's semantic judgement) — plus the Phase 3
hardening suite: preflight budget estimation, runtime limits, transient
error recovery (rate limit / timeout keeps a project resumable instead
of failing it), model fallback recording, cancellation and
budget-exhaustion terminal no-ops, structured run logs, terminal-status
mapping, the extended claim-outcome vocabulary, and 10 further
adversarial research cases (fabricated citation, unrelated content,
wrong arithmetic, missing fee, outdated pricing, contradictory sources,
inaccessible page, misleading snippet, fabricated quotation,
unsupported profitability assumption).

## Cost controls and observability (Phase 3)

- **Preflight estimation:** before every LLM call, the estimated cost
  (input tokens from text length + `AR_ESTIMATED_OUTPUT_TOKENS`,
  default 1500) is checked against the remaining budget. The first call
  of a project is never preflight-blocked, so a too-small budget cannot
  deadlock a run before any work exists. Completed calls record actual
  token usage from the provider response.
- **Runtime limit:** `AR_MAX_RUNTIME_S` (default 3600) fails a run with
  artifacts preserved when exceeded.
- **Transient recovery:** timeout / rate-limit / temporary-overload
  errors leave the project in its current non-terminal state with a
  `transient_error` in the run result, so a later `resume` continues.
  Permanent errors still fail the run as FAILED.
- **Model fallback:** `AR_MODEL_FALLBACK` names a model used only when
  the provider reports the configured model unavailable. The model that
  actually executed is recorded in `run_metadata.json` (`models_used`).
- **Structured log:** every project writes `run_log.jsonl` (transitions,
  LLM calls with tokens and estimated cost, search calls, transient
  errors). No prompts, keys, or secrets are logged.
- **Terminal labels:** `status` and `run_metadata.json` report both the
  state machine state and the spec §15.1 label (`COMPLETED_APPROVED`,
  `COMPLETED_WITH_LIMITATIONS`, `FAILED_VALIDATION`,
  `FAILED_EXECUTION`, `CANCELLED`, `BUDGET_EXHAUSTED`).
- **Completion notification:** set `AR_NOTIFY_CMD` to a command invoked
  (without a shell) with the project id and terminal state when a `run`
  finishes.
- **Search charges:** web_search calls are counted; when
  `AR_TAVILY_COST_PER_SEARCH` is set (> 0), each search is added to
  project spend. Default 0 bills nothing rather than inventing a price.
- **Concurrency and retries:** the CLI is single-threaded (max one paid
  request in flight by construction). API retries are bounded: one
  schema fallback, one model fallback, one validation-repair retry; no
  unbounded retry loop exists anywhere.

## Known limitations (honest list)

- **No live end-to-end run has been executed here**: it requires a real
  `OPENAI_API_KEY`, which was not available in this environment. The
  live test exists (`tests/test_integration.py::test_live_end_to_end`)
  and is skipped without a key. Do not treat the stub demo as research.
- Keyless DuckDuckGo search is unreliable (bot-guard pages); use
  `TAVILY_API_KEY` for real research.
- Budget figures are estimates from token counts and configured prices;
  the provider's actual bill governs.
- The auditor's independent verification checks passage presence in
  re-fetched pages; it does not re-derive every calculation or verify
  paywalled sources.
- `AR_ALLOW_CODE_EXECUTION` is accepted by config but no code-execution
  tool ships in this release; generated code is never executed.
- Exact-once execution against external APIs is not claimed: if a
  process dies mid-API-call, resume may repeat that call. Step outputs
  are idempotent; external side effects are not.

CLI `run` / `resume` exit 0 only for clean `COMPLETED`, 1 for other outcomes
(including limitations or transient interruption), and 2 for argument/provider
configuration errors. Status/report inspection commands do not start research.
