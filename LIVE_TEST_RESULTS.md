# Live Test Results — Phase 2

## Result: NOT RUN — no credentials available

On October 28, 2026, credential presence was checked without reading,
printing, or storing any secret value:

- `OPENAI_API_KEY`: absent from the environment; no `.env` file in the
  repository.
- `TAVILY_API_KEY`: absent from the environment.

No live API call was made, no live research was conducted, and no live
result is claimed anywhere in this audit. In particular, the auditor was
**not** observed independently verifying material claims on a live run,
because no live run exists.

## Exact commands to run the live test

```bash
cd ~/workspace/autonomous-research
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY="..."      # your key; never commit it
export TAVILY_API_KEY="..."      # recommended for reliable search
export AR_RUN_LIVE=1

# Option A — the automated live test (small objective, mini models):
AR_RUN_LIVE=1 .venv/bin/python -m pytest tests/test_integration.py::test_live_end_to_end -q

# Option B — the full Phase 2 assignment, end to end:
.venv/bin/python main.py run "Identify three realistic, legally permissible, AI-assisted commodity arbitrage business models that could be started with less than \$2,000. Evaluate actual transaction economics, acquisition costs, platform restrictions, operational risks, and the feasibility of automation. Reject opportunities without sufficient supporting evidence."
```

Then inspect, in the created `projects/<PROJECT_ID>/` directory:

- `final_report.md` — sections 1–9, and whether rejected opportunities
  are actually rejected (not merely hedged).
- `audit_report.json` — `verified_sources` must list sources the code
  re-fetch confirmed, and `unverified_sources` the rest.
- `execution_report.md` / `sources.json` — every material claim should
  cite a retrieved source with a passage; classifications should not
  claim VERIFIED for unconfirmed sources (the claim analyzer now blocks
  that path mechanically).
- `run_metadata.json` — state, revision/correction counts, and real
  spend vs. the $10 target.

## Pass criteria for the live test (to be recorded here after it runs)

1. Run reaches `COMPLETED` or `COMPLETED_WITH_LIMITATIONS` (the latter
   is acceptable only if the limitations section names real unresolved
   issues).
2. At least three candidate business models evaluated with transaction
   economics grounded in cited, re-fetch-confirmed sources.
3. At least one opportunity rejected for insufficient evidence, if the
   evidence warrants it — or an explicit statement of why none was.
4. No claim classified VERIFIED rests solely on an UNREACHABLE or
   NOT_FOUND source.
5. Real spend recorded in `run_metadata.json` is reported, whether or
   not it is within $10.
6. Calculations in the report are reproducible from the stated inputs
   (auditor's mathematical-correctness check).

## What was verified without live credentials (so the live run is not starting from zero)

- Full mechanical workflow (45 tests passing, 1 skipped live test).
- Strict-mode schema compliance for every contract (previously a
  guaranteed live 400).
- Claim-support analyzer blocking VERIFIED-without-confirmed-source and
  dangling citations.
- Verification facts persisted from code, not LLM assertions.
- Search tool behavior: Tavily path (mocked HTTP) works; DuckDuckGo path
  fails honestly when bot-guarded.
- SDK surface verified by introspection (Responses API parameters,
  `output_text`, usage token fields) against openai 3.40.0.

---

## Phase 3 attempt (October 28, 2026): still NOT RUN

Credential presence re-checked (presence only, no values read, printed,
or stored): `OPENAI_API_KEY` absent, `TAVILY_API_KEY` absent, no `.env`
file. No live call was made and no live result is claimed.

Additionally, no total validation spending ceiling has been authorized.
Per the mandate, paid live tests require explicit approval. Proposed
ceiling: **$30 total** (up to 3 live attempts at the $10 per-project
cap), based on estimated live cost of roughly $1–5 per project at
verified prices (gpt-5.4-mini $0.75/$4.50, gpt-5.6-terra $2.00/$12.00
per 1M tokens).

To unblock, the user must: (1) provide the API keys via the secure
environment (never in chat), and (2) approve the $30 ceiling. On
approval, run the commands in the "Exact commands" section above, then
record results against the pass criteria — including real spend from
`run_metadata.json` and the OpenAI usage dashboard.

---

## Phase 4 attempt (October 28, 2026): still NOT RUN — CREDENTIAL_MISSING

Spending authorization received this phase: **$30 total, $10 per
project, max 3 live attempts** (OpenAI + Tavily only). Authorization
alone does not create credentials.

Credential check (presence only): environment variables absent; repo
`.env` absent; `~/.env`, `~/workspace/.env`,
`~/.config/autonomous-research/.env` absent. Smoke script
(`scripts/smoke_live.py`) exited 2 with `CREDENTIAL_MISSING` and $0.00
recorded in the new cumulative ledger (`python main.py ledger`:
$0.0000 of $30.00, 0 entries).

No live connectivity test, live research project, or generalization
test was executed. Total Phase 4 validation spending: **$0.00**.

Preparation completed so the live phase can start immediately once
credentials exist: `.env` loading implemented and tested, cumulative
ledger + dual-cap preflight implemented and tested, smoke script ready,
all 72 tests passing. The commodity-arbitrage objective and the B2B
generalization objective are recorded in `FINAL_ACCEPTANCE_REPORT.md`
(Phase 4 addendum) for the resumption run.

---

## First genuine live run (user's Mac, October 28, 2026): FAILED — now fixed

- **Project:** `17833c7a8172` (user's local installation).
- **Error:** `OpenAI Responses API call failed: Error code: 400 -
  Response input messages must contain the word 'json' in some form to
  use 'text.format' of type 'json_object'.`
- **Observed state:** FAILED, 0 prompt revisions, 0 corrections,
  0 tool calls, $0.0053 recorded.
- **Root cause (defect D-27):** strict mode was rejected for some agent
  step, the `json_object` fallback fired, and the fallback request
  lacked the word "json" in its input messages. Fix applied in
  `src/llm/provider.py` (see `REMEDIATION_LOG.md` R-23); full suite
  79 passed, 1 skipped. Which agent step's strict call was rejected
  cannot be determined from the reported summary alone; the fix covers
  all agents because all go through `OpenAIProvider.complete`, and the
  strict error is now preserved in failure messages for diagnosis.
- **Live re-test:** NOT yet executed (no credentials in this
  environment). The user's next live `run` after installing the fix is
  the live confirmation; it must be a new project, since FAILED is
  terminal and `17833c7a8172` cannot be resumed.

---

## Second live run (user's Mac, October 28, 2026): FAILED — now fixed

- **Project:** `c9b4973708ec` (user's local installation).
- **Error:** `model returned non-JSON output:
  {"tool":"web_search","query":"site:shopgoodwill.com LEGO bulk auction used price","max_results":5}{"tool":"web_search","arguments":{"query":"site:shopgoodwill.com LEGO bulk auction used price","max_re...`
- **Observed state:** FAILED, 1 prompt revision, 0 corrections,
  0 tool calls, $0.0126 recorded.
- **Root cause (defect D-28):** the executor's tool calls travelled as
  model-written JSON text. In the json_object fallback the envelope
  schema is unenforced, so the model emitted bare tool objects in two
  formats and concatenated them; the provider rejected the text, and
  `call_agent` gave non-JSON output zero repair attempts. Fix: native
  Responses API function calling for the executor (see
  `REMEDIATION_LOG.md` R-24); full suite 94 passed, 1 skipped.
- **Live re-test:** NOT yet executed (no credentials in this
  environment). The user's next live `run` after installing the fix is
  the live confirmation; it must be a new project, since FAILED is
  terminal and `c9b4973708ec` cannot be resumed.
