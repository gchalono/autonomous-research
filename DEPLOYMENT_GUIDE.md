# Deployment Guide — macOS local execution

This is a local CLI application. No web dashboard, no public deployment,
no paid external service beyond the model and search APIs themselves.

## 1. Install

```bash
cd ~/workspace/autonomous-research
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in real keys; .env is git-ignored
```

Requirements: Python 3.12+, `pydantic`, `openai`. Verified with Python
3.12.3, pydantic 2.14.1, openai 3.40.0, pytest 9.2.0.

## 2. Configure

`.env.example` contains placeholders only. The application loads the
repo's `.env` file automatically at startup (real environment variables
take precedence over `.env` values); no other file is read for
credentials. Required for live research:

| Variable | Where to get it | Notes |
|---|---|---|
| `OPENAI_API_KEY` | [OpenAI API keys](https://platform.openai.com/api-keys) | Never commit; never paste into chat or logs. |
| `TAVILY_API_KEY` | [Tavily](https://tavily.com/) (free tier available) | Recommended: keyless DuckDuckGo scraping is unreliable. |

Optional tuning (defaults in parentheses):

- `AR_BUDGET_USD` (10.0) — per-project spending target.
- `AR_MODEL_CREATOR` / `AR_MODEL_EVALUATOR` (`gpt-5.4-mini`),
  `AR_MODEL_EXECUTOR` / `AR_MODEL_AUDITOR` (`gpt-5.6-terra`) —
  re-verify ids against OpenAI's model list before a production run.
- `AR_MODEL_FALLBACK` (unset) — model used only if a configured model
  is reported unavailable; the model actually used is recorded.
- `AR_MAX_RUNTIME_S` (3600), `AR_MAX_PROMPT_REVISIONS` (3),
  `AR_MAX_CORRECTIONS` (2), `AR_MAX_TOOL_ITERATIONS` (12),
  `AR_MAX_SOURCES_TO_VERIFY` (8), `AR_ESTIMATED_OUTPUT_TOKENS` (1500),
  `AR_TAVILY_COST_PER_SEARCH` (0 = count only), `AR_NOTIFY_CMD` (unset).

The shell must export these variables (or they must be in `.env` loaded
by your shell) — the application reads the environment only and never
writes keys anywhere. Secrets never appear in `run_log.jsonl`, artifacts,
or error messages; the provider SDK sends the key over HTTPS only.

## 3. Run a project

```bash
python main.py run "Research objective"
python main.py status <PROJECT_ID>
python main.py report <PROJECT_ID>
python main.py resume <PROJECT_ID>
python main.py cancel <PROJECT_ID>
python main.py ledger   # cumulative validation spending vs. the $30 cap
python scripts/smoke_live.py  # minimal live connectivity checks
```

A run is unattended: it proceeds through prompt creation, evaluation,
execution, audit, and correction without interaction, then prints a
`DONE: ...` line with the terminal state. Artifacts live in
`projects/<PROJECT_ID>/`: `final_report.md`, `sources.json`,
`audit_report.json`, `run_metadata.json`, `run_log.jsonl`, plus
versioned prompts and audit reports.

## 4. Interpret the outcome

- `COMPLETED` / `COMPLETED_APPROVED` — auditor approved; still read
  sections 6–8 (limitations, audit outcome, unresolved issues) before
  acting on findings.
- `COMPLETED_WITH_LIMITATIONS` — correction limit reached with major or
  critical issues open; the final report lists them. Do not treat as
  clean success.
- `BUDGET_EXHAUSTED` — spending guard fired; intermediate artifacts
  (prompts, partial reports) are preserved; resume after raising the
  budget only if you intend to spend more.
- `FAILED` — read `failure_reason` in `status` output; `FAILED_VALIDATION`
  means the prompt itself was blocked or exhausted revisions,
  `FAILED_EXECUTION` means a later stage failed.
- Transient errors (rate limit, timeout) do NOT fail a run: `resume`
  continues from the current state.

## 5. Cost expectations (estimates, not guarantees)

Per-project budget default is $10. With current verified pricing
(gpt-5.4-mini $0.75/$4.50, gpt-5.6-terra $2.00/$12.00 per 1M input/output
tokens), a typical run — creator, evaluator, ~12 executor turns with a
capped 60k-char transcript, auditor, plus up to 2 correction cycles —
is estimated at roughly $1–5. The provider's bill governs; check
`run_metadata.json` (`spent_usd` is estimated from reported token usage)
against your OpenAI usage dashboard after live runs. Set a total
validation ceiling across projects yourself: the per-project cap does
not limit how many projects you launch.

## 6. Before first production use

1. Run the test suite: `.venv/bin/python -m pytest tests/ -q`.
2. Run one supervised live project and read its full audit trail.
3. Confirm model ids, prices, and Tavily billing on the providers'
   own pages.
4. Decide your total spending ceiling across live projects.
