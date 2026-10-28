# Bounded live validation

**Not yet run against live APIs for this revision.** Offline mocks demonstrate
mechanics, not genuine research. The two earlier local runs failed; existing local
OpenAI/Tavily connectivity does not prove the native workflow now completes.

Do not run the paid commands below until you authorize their spending. Neither
credentials in `.env` nor historical spending authorization count as approval for
this audit. The runner refuses to start without `--authorize-paid-run`.

## Prerequisites

Use the existing checkout and virtual environment on the machine where credentials
already work. The runner loads the repository `.env` without overwriting exported
variables. Do not paste, print or commit credentials. Required variable names:
`OPENAI_API_KEY`, `TAVILY_API_KEY`.

Select a model currently available to those credentials and verify its current
input/output prices and your Tavily per-search cost. The example below uses the
repository's creator model and illustrative rates already present in its config;
**these are not verified current availability/pricing**. Replace the model and
rates if needed. There is no automatic model fallback in the bounded runner.

Required destinations are `api.openai.com`, `api.tavily.com`, the selected official
source (`docs.python.org` for this objective), and any search-selected source or
redirect hosts. Use an egress allowlist on machines handling untrusted URLs. Do not
start broad arbitrage research as this first validation attempt.

## One attempt after authorization

From the existing repository directory, run:

```bash
# Offline prerequisites; these make no paid calls.
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m pip check

# Paid only when explicitly authorized. Reuse this projects root on retries:
# changing roots resets the scope of the local cumulative ledger.
AR_PROJECTS_ROOT=projects .venv/bin/python scripts/validate_live.py \
  --authorize-paid-run \
  --model gpt-5.4-mini \
  --input-usd-per-million 0.75 \
  --output-usd-per-million 4.50 \
  --search-usd-per-call 0.01 \
  --budget 1.00 \
  --total-budget 2.00
```

This runs one small research project using real APIs, with one prompt revision,
one audit correction, at most six executor turns per execution attempt, two
independently checked sources, 4,000 output tokens per model request, 45s model
timeouts, and a five-minute project runtime gate. All roles use the chosen model.
Every actual provider request is preflighted, including strict-format/model
fallbacks in the ordinary application; automatic SDK retries are disabled. Search
charges are recorded at the supplied rate. The runner does not automatically
resume or start another project after failure.

The $1 project/$2 cumulative values bound **estimated** charges. They are not a
hard provider billing limit: token estimates, timeout billing, discounts and
price changes can differ. Set provider-side limits for a hard account boundary.
Keep the existing ledger; do not delete it or change projects roots to bypass a
cap. An existing total above $2 will prevent further requests until an explicitly
authorized ceiling is changed.

## Evidence and exit status

The script prints the project id, final state, behavioral checks and ledger
summary. It writes `projects/<ID>/live_validation.json` alongside the normal
artifacts. Exit 0 requires all of: clean COMPLETED status, a successful search,
page fetch and calculation, at least one independently confirmed source, and an
existing final report. A limitations outcome, transient interruption or failed
behavioral check exits 1. Missing authorization/credentials/invalid prices exit 2.
No secrets are printed.

Inspect without starting another paid run:

```bash
.venv/bin/python main.py status <PROJECT_ID>
.venv/bin/python main.py report <PROJECT_ID>
.venv/bin/python main.py ledger
```

Read `final_report.md`, `audit_report.json`, `sources.json`, `run_metadata.json`,
`run_log.jsonl` and `live_validation.json`. Confirm the documented claim is actually
supported by the independently fetched passage and that the calculation is
correct. Compare local estimates with provider billing. A mechanically passing
probe does not establish general research quality or production readiness.

Do not blindly resume via ordinary CLI defaults: the bounded runner deliberately
uses tighter settings and explicit prices. A subsequent paid retry needs its own
authorization and should use the same runner/ledger and verified prices. Terminal
FAILED projects cannot resume. Native transient checkpoints remain available for
a deliberate resume with matching settings in a separately authorized session.

The older `scripts/smoke_live.py --authorize-paid-run` checks connectivity only,
requires a positive `AR_TAVILY_COST_PER_SEARCH`, and enforces the cumulative cap.
It is not needed before the bounded full workflow when local connectivity is
already known, and is not proof of autonomous execution.
