# Independent review and acceptance gate

Verdict: **NOT READY** for a paid live test in the current cloud instance.
The offline software acceptance checks pass. The remaining prerequisites are
working source DNS, configured OpenAI/Tavily credentials, allowed API destinations,
and account-specific model/pricing verification. No API credits were spent.
No successful genuine research run is claimed. Use the Mac procedure in
[LIVE_VALIDATION.md](LIVE_VALIDATION.md) after satisfying those prerequisites and
separately authorizing one paid attempt.

## PR #1 review

Reviewed main `1b2f809911445cfb46cea8a1c228993e8d30fe2a`, PR #1/head and
`fix/autonomous-workflow-audit` at
`44c4d0b0a780820c17b19cc0d63e3b7dfbce90ba`, their complete diff, the PR's web
page/description, ENGINEERING_AUDIT.md and LIVE_VALIDATION.md. PR #1's head and
the named branch are the same commit. GitHub API access returned Forbidden;
this is a local written review, not a posted GitHub approval/review.

Recommendation on PR #1 as reviewed: **request changes**. Native function
calling, bounded repair, independently fetched evidence, effective audit
persistence, shared-root locking, and fail-closed accounting are useful
improvements over main. However, the completion and recovery claims were too
broad: unconfirmed derived claims could receive clean completion, and the
native checkpoint still had a reproducible duplicate-tool window. The old
live-runner test accepted unrelated fee research for a Python objective.
The changes on `fix/independent-live-readiness` address the findings below.
This branch is based on PR #1, intended as a follow-up PR targeting its branch;
neither main nor PR #1 was merged or rewritten.

Independently reproduced main's initial 94 passed / 1 skipped and PR #1's
142 passed / 1 skipped. The former was reproduced earlier in this same task;
the latter was rerun after fetching the exact PR head, before corrections.
Historical test counts are not evidence of a successful live run.

## Prioritized defect register

| ID | Severity | Reproduction and root cause | Correction / regression |
|---|---|---|---|
| IR-1 | High | Change a claim to INFERRED, ESTIMATED, PARTIALLY_SUPPORTED or CONTRADICTED, give it an UNREACHABLE source, and let the auditor approve. No blocking code issue existed: only VERIFIED required confirmed evidence. | Require confirmed external evidence for derived/evidence-based claims. `test_unconfirmed_evidence_cannot_support_derivation` reproduced all four failures before the fix. Pure arithmetic now explicitly references successful calculator expressions, and the auditor receives actual calculator outputs. Missing calculation references block approval. |
| IR-2 | High | Interrupt after the search/tool database commit but before the native transcript checkpoint, reopen SQLite and resume. The search and its charge repeated. The prior test interrupted the next model request, missing this window. | Atomically commit the tool row, project charge, and full replayable result keyed by execution attempt/turn/call position. Replay that result without invocation or charge. `test_scenario_c_crash_after_tool_commit_before_transcript_checkpoint` failed with two searches before the correction and now passes with one. This does not promise exactly-once remote calls before local commit. |
| IR-3 | High | The old bounded test used ResearchSDK's unrelated net-fee report and still returned exit 0 for the Python fact objective. Checks tested only generic successful tools and any confirmed source. | Check the specific official source, linked factual claim and observed/reported `2 + 3 = 5`. The old fixture is now an explicit negative test. Switch to short upstream constants documentation so the reference is within the retrieval cap; preflight it without paid requests. |
| IR-4 | High | `max_tool_iterations` bounds turns, not tool calls: a response may contain many function calls. Model repairs and format fallbacks also consume additional requests. | Persist a per-project model request count, enforce a project-wide tool-call count, and include retries/corrections/resumes. Ordinary defaults are 48 each; bounded runner uses 20 model requests and 6 dispatched tools. `test_request_and_tool_caps_survive_resume` failed before the change. |
| IR-5 | Medium | Disable the best-effort run log and inspect the ledger: it retained cost but lost observed token counts. | Store token counts, response id and the full SDK usage object in the persistent ledger, including cached/reasoning details when returned. `test_usage_survives_missing_run_log` reproduced the loss; the real-SDK scenario checks exact input/output/reasoning totals. Old entries remain intact and are not invented retroactively. |
| IR-6 | Medium | Raise an SDK response validation error with HTTP 200 and the word schema. Both provider paths treated it as a rejected request schema and issued a second request, potentially duplicating spend. | Format fallback now requires HTTP 400 when a status is supplied; model fallback requires 400/404. Two parameterized regressions fail before and pass after the fix. Unknown remote usage remains unknown. |

All listed code defects have targeted regression coverage. IR-1 also exposed
that a pure arithmetic claim previously needed a gratuitous web citation:
`Claim.calculation_expressions` is an optional, backward-compatible reference
to recorded successful calculator calls. It establishes computation provenance,
not the truth of external inputs or the semantic correctness of a claim.

## Three independent scenarios

All scenarios use actual orchestration, prompts, native dispatch, search and
retrieval adapters, calculator, independent audit, SQLite, ledger and artifacts.
No paid endpoint is contacted by these tests.

- **A — success:** `test_scenario_a_bounded_success_through_real_sdk_http_contract`.
  Creator → evaluator approval → native search → official-source retrieval →
  calculation → report → independent refetch/auditor approval → COMPLETED.
  Uses the installed OpenAI SDK with strict response DTO validation over a mocked
  HTTP transport. Real SDK JSON serialization/deserialization runs; function
  call/output ids and opaque reasoning items survive continuation. Seven model
  responses record exactly 700 input, 350 output and 70 reasoning tokens. DNS,
  model answers, OpenAI HTTP and Tavily/source HTTP are mocked. A free source
  preflight is additional to the executor/auditor fetches.
- **B — incorrect research:** `test_scenario_b_incorrect_research_is_corrected`.
  Initial report plausibly says net 12 while independently fetched evidence
  specifies a fee of 2. Auditor requires correction; executor calculates 12 - 2;
  second audit explicitly resolves the original issue and approves net 10.
  SDK responses, DNS and external HTTP are mocked; orchestration/dispatch and
  all local storage/rendering are real. The existing fixture also exercises a
  prompt revision. This scenario runs separately from interruption recovery.
- **C — infrastructure failure:**
  `test_scenario_c_crash_after_tool_commit_before_transcript_checkpoint`.
  Inject KeyboardInterrupt after the completed search's local commit, discard
  the connection, reopen SQLite, and resume. Exactly one search/tool row/search
  charge remains, evidence reaches the next executor request, accounting agrees,
  and correction/audit complete. Only SDK/HTTP/DNS and the crash boundary are
  mocked. The prior timeout-on-next-model-request scenario remains covered too.

Native request definitions and returned SDK DTOs are validated offline; actual
server strict-schema acceptance, model authorization and live reasoning
continuation still require the bounded paid attempt. Offline tests are not
substitutes for those checks.

## Commands and results

From `/workspace/autonomous-research` with Python 3.12.14, OpenAI 3.40.0,
pydantic 2.14.1 and pytest 9.2.0:

```sh
.venv/bin/python -m pytest tests/ -q
# 155 passed, 1 skipped (opt-in live test)
.venv/bin/python -m pytest tests/test_independent_review.py -q
# 13 passed
.venv/bin/python -m pip check
# No broken requirements found.
git diff --check
# exit 0, no whitespace errors
```

Failing pre-fix reproductions were run for evidence, crash replay, missing
usage, request caps and erroneous schema fallback. Those expected failures
are not counted as passes. Existing malformed-JSON, schema fallback, invalid
function arguments, prompt correction, cancellation, budget, redirect/SSRF,
artifact confinement, and adversarial suites remain enabled.

## Acceptance decision and remaining limitations

| Gate | Evidence / result |
|---|---|
| Complete offline suite | Pass, 155 passed / 1 live skipped |
| Independent A/B/C scenarios | Pass |
| Native API contract as far as offline permits | Pass, actual SDK/HTTP DTO transport test plus existing fallback tests |
| Known critical code defect in reviewed bounded path | None identified after corrections; this is scoped evidence, not a proof |
| Bounded runner functional and safe offline | Pass: authorization required, positive finite explicit prices, real provider only, one attempt, no auto-resume, 20 requests/6 tools total, capped estimated spending, observed usage and failure evidence retained |
| Current machine can start a genuine bounded run | **Fail**: credentials absent, API hosts not currently granted, source pre-resolution fails locally |

A read-only application call to `fetch_url(SOURCE_URL)` failed with
`socket.gaierror: Temporary failure in name resolution`. Curl downloaded the
same public CPython documentation through the inherited proxy, so this is a
proxy/local-DNS mismatch, not evidence that the source is absent. The application
requires DNS for SSRF checks before urllib uses the proxy. Preserve that check;
run on a machine with working public DNS or provide a supported DNS/egress setup.
The bounded runner now detects this for free before model requests. Missing
credentials and API host grants are additional cloud prerequisites. API keys
must be configured securely, never pasted into chat. OPENAI_API_KEY is a reserved
platform secret target, so the generic draft secret tool cannot bind it by name.

Model availability and current prices could not be verified against the live
account or authoritative pricing pages in this environment. The installed SDK
recognizing an id does not prove the account can use it. Verify the desired
model's Responses/function-calling/structured-output support and current input,
output, cached/long-context/reasoning rates; choose conservative rates and check
Tavily's actual per-query charge. No silent fallback model is configured in the
bounded runner.

Other limits remain explicit:

- LLM semantic judgement can miss an unsupported premise or uncited narrative;
  regex tripwires and untrusted-data labels are not an injection sandbox. The
  bounded gate checks a known fact and calculation, not arbitrary research quality.
- A crash after a remote action but before its local commit can still repeat it.
  Timeout charges with no returned usage cannot be observed locally. A split
  database/ledger crash reconciles retained cost totals but may not recover
  usage details. Provider-side limits and billing reconciliation remain necessary.
- Model request counts reserve an attempt before dispatch; a crash there may
  conservatively consume a slot. Historical projects lack earlier request counts.
  Full native tool replay applies to new committed results, not legacy JSON loops
  or pre-upgrade partial checkpoints.
- Public-DNS validation still has a resolution/connection race. Use an actual
  egress policy; built-in tools are read-only, no generated code runs. Socket
  timeouts are not hard wall-clock deadlines for trickle responses. Cancellation
  cannot interrupt an in-flight request.
- Source count, page byte/text caps, PDFs/paywalls/JavaScript and search failures
  limit coverage. Multiple projects roots have separate ledgers; retain the
  existing root and history. Arithmetic evidence proves only an expression was
  executed; its meaning/inputs still need audit.
- This is neither a production acceptance nor a completed live acceptance. No
  paid calls were authorized or made. Publication of the cloud snapshot and
  successful restoration in another task have not been verified.
