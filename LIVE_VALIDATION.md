# One bounded live acceptance attempt

Current verdict: **NOT READY in the current cloud instance**. See
[INDEPENDENT_REVIEW.md](INDEPENDENT_REVIEW.md) for the independent PR review,
defect register, exact offline evidence and outstanding operational blockers.
No genuine live run has succeeded on this revision, and no credits were spent.

## Update the existing Mac installation

Use your existing checkout, virtual environment, `.env`, projects directory and
ledger. Stop if `git status --short` lists local edits you have not preserved;
do not reset, clean, delete history, or merge either audit branch into main.
From your existing `autonomous-research` directory:

```sh
git status --short
git fetch origin refs/heads/fix/independent-live-readiness:refs/remotes/origin/fix/independent-live-readiness
git switch fix/independent-live-readiness
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pip check
.venv/bin/python -m pytest tests/ -q
```

Expected offline result: **155 passed, 1 skipped**. Git switch uses the existing
local branch or creates a tracking branch when only that remote branch exists.
Python 3.12 is the tested runtime. Retained `.env` values are loaded normally;
exported variables take precedence. Never print or commit keys.

## Verify prerequisites without spending credits

OpenAI and Tavily credentials must already work securely on this Mac. Confirm
current model authorization and Responses/native function/structured-output
support in your provider account. Verify current prices at
<https://openai.com/api/pricing/> and your Tavily plan. Historical repository
prices and SDK model enums do not prove current availability or billing rates.

This short check prints names/presence only and makes one free read-only fetch:

```sh
.venv/bin/python - <<'PY'
import os
from src.config import load_dotenv
from src.tools.retrieval import fetch_url
from scripts.validate_live import SOURCE_URL
load_dotenv()
missing = [n for n in ('OPENAI_API_KEY', 'TAVILY_API_KEY') if not os.environ.get(n)]
if missing:
    raise SystemExit('Missing configuration: ' + ', '.join(missing))
_, text = fetch_url(SOURCE_URL)
assert 'sole instance' in text and 'NoneType' in text
print('Credential names present; official source fetch works. No paid request made.')
PY
```

If source preflight fails, fix public DNS, TLS trust, or egress on that machine;
do not disable TLS/SSRF verification. Required API hosts are `api.openai.com`
and `api.tavily.com`; the explicit official source is under
`raw.githubusercontent.com`. Search-selected sources/redirects may require their
own domain grants. The cloud instance currently lacks API credentials/grants
and its local DNS fails despite working proxy downloads. This does not prove
anything about the Mac's network or credentials.

## Run exactly once, only after explicitly authorizing spending

Set four **non-secret** shell variables to the model and prices you verified:
`LIVE_MODEL`, `LIVE_INPUT_USD_PER_MILLION`, `LIVE_OUTPUT_USD_PER_MILLION`, and
`LIVE_SEARCH_USD_PER_CALL`. Use conservative rates that cover your model's
applicable billing categories. The command below deliberately refuses missing
values. It authorizes one attempt with $1 project / $2 cumulative **estimated**
limits; it does not authorize another run or automatic resume.

```sh
: "${LIVE_MODEL:?Set a model verified in your provider account}"
: "${LIVE_INPUT_USD_PER_MILLION:?Set the verified input price}"
: "${LIVE_OUTPUT_USD_PER_MILLION:?Set the verified output price}"
: "${LIVE_SEARCH_USD_PER_CALL:?Set your Tavily query cost}"
AR_PROJECTS_ROOT="${AR_PROJECTS_ROOT:-projects}" .venv/bin/python scripts/validate_live.py \
  --authorize-paid-run \
  --model "$LIVE_MODEL" \
  --input-usd-per-million "$LIVE_INPUT_USD_PER_MILLION" \
  --output-usd-per-million "$LIVE_OUTPUT_USD_PER_MILLION" \
  --search-usd-per-call "$LIVE_SEARCH_USD_PER_CALL" \
  --budget 1.00 --total-budget 2.00
```

The runner preflights the official source before any paid request. It then runs
one real project: research the documented fact that None is the sole instance
of NoneType and separately calculate 2 + 3 = 5. It uses one chosen model for all
roles, no model fallback, at most 20 model request attempts and 6 dispatched
tools across the whole project, one prompt revision, one audit correction, six
executor turns per execution attempt, two independently checked sources,
4,000 output tokens per model request, 45s model timeout and a five-minute
runtime gate checked between operations. SDK retries are disabled. Format
fallback/repair attempts count against the request cap. No stub is selected.

Do not change projects roots to evade the cumulative cap. If your historical
ledger already exceeds $2, the estimated-cost gate refuses further spending.
Changing the ceiling needs a new explicit authorization. The estimates are
not hard billing guarantees; configure provider-side account limits too.

## Inspect results without another paid run

The runner prints the project id and writes `<projects_root>/<ID>/live_validation.json`
alongside the reports, sources, audit, run log and metadata. Inspect with:

```sh
.venv/bin/python main.py status <PROJECT_ID>
.venv/bin/python main.py report <PROJECT_ID>
.venv/bin/python main.py ledger
```

Keep the same `AR_PROJECTS_ROOT` for these commands if it was overridden.
Exit 0 requires clean COMPLETED plus an approving effective audit; successful
search; fetch of the exact official source; a linked VERIFIED None/NoneType
claim supported by that independently confirmed source; observed calculation
2 + 3 = 5 and a corresponding linked report claim; final report; recorded
observed model usage; and no unhandled runner error. Unrelated approved research
fails acceptance. Read the actual passage, claim and calculator output anyway:
these structural checks cannot replace semantic review.

Exit 1 means behavioral failure, limitations, interruption or a retained runtime
diagnostic; exit 2 means missing authorization/configuration, invalid prices or
failed free source preflight. A failure does not automatically start another
project or resume. Inspect history and provider billing first. Never resume
this bounded project through ordinary CLI defaults, which use different limits
and prices. A retry requires separate authorization with matching settings and
the retained ledger. Old ledger entries remain unchanged; new entries preserve
response ids, token totals and the full usage object when observed. A remote
call can be billed without returning usage, and a crash before local commit
still prevents an exactly-once guarantee.
