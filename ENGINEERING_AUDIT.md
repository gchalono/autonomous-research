# Engineering audit and implementation

This records PR #1 as originally audited. The subsequent independent review,
corrections and current verdict are in [INDEPENDENT_REVIEW.md](INDEPENDENT_REVIEW.md).

Current assessment: the native research workflow is demonstrated offline through
revision, real tool adapter dispatch, independent verification, correction, and
resume. Real API-backed end-to-end execution remains **unverified**. This is
not a production-readiness claim. Historical audit/acceptance documents describe
earlier revisions; this document and [LIVE_VALIDATION.md](LIVE_VALIDATION.md)
are the current engineering handoff.

## Architecture inspected

The CLI loads local configuration, chooses a provider, and invokes a deterministic
state machine. Creator/evaluator/auditor use schema-validated responses. The
OpenAI executor uses Responses function items and `submit_report`; only clients
without native support use the legacy JSON envelope. Tool code enforces action
permissions, while SQLite owns project state, outputs, events, issues, and tool
history. Independent refetch establishes passage presence, deterministic claim
analysis checks citation structure and retrieval provenance, and the auditor
judges semantic support. Reports are rendered from persisted results. A shared
JSON ledger tracks cumulative estimated charges.

Inspected all application modules, CLI/scripts, test suites, dependency manifests,
configuration, and deployment/audit documentation. Existing components were
retained; fixes target failures in their boundaries and bookkeeping.

## Confirmed defects corrected

| Area | Before | Correction and regression evidence |
|---|---|---|
| Provider fallback | JSON fallback requested an unspecified schema; every HTTP 400 could trigger fallback. | Include the complete schema and JSON instruction; retry format only for schema/format failures. Existing exact-400 tests plus fallback regressions. |
| Paid response accounting | Malformed JSON bypassed accounting; fallback usage was charged at the requested model; SDK retries were hidden. | Gate and charge each actual provider request, before parsing, using its candidate model. Disable SDK retries; set `max_output_tokens`; account incomplete responses. |
| Agent repair | A malformed response followed by invalid schema could trigger a third call. | One total repair across parsing and schema validation, preserving transient recovery. |
| Native execution | Mixed submit/tool turns could finish without executing the research; transient interruption replayed completed search work. | Accept submission only as a sole function call. Persist rounds, pending response and completed tool outputs; resume them without replaying completed actions. |
| Context management | A single large latest native round could be dropped entirely. | Retain the latest complete call/output round and drop older complete rounds. The latest round can exceed the nominal character target; request preflight still sees its full size. |
| Audit issue lifecycle | Empty later APPROVE silently bypassed prior blocking issues; IN_PROGRESS/UNRESOLVED were ignored. | Give the auditor prior issues, require explicit resolution for auditor-owned issues, gate on all unresolved merged issues, and persist the effective decision. |
| Code findings | Sequential CC ids could identify different defects after correction; fixed code findings remained open. | Stable code-owned ids; recompute findings and resolve only code defects that no longer reproduce. LLM cannot override current code findings. |
| Evidence verification | Only the first 60 normalized characters of a quotation were checked; auditor saw no fresh surrounding context. | Match the entire normalized passage and supply bounded, independently fetched context as untrusted data. Checkpoint verification with the audit so resume uses the same evidence snapshot. |
| Citation integrity | Unretrieved sources were only minor findings; duplicate source/claim/finding ids and missing finding-to-claim mappings could pass. | Block on provenance gaps and ambiguous/broken identity mappings. A full re-execution starts a new retrieval-provenance boundary; targeted corrections may reuse prior evidence. |
| Completion status | Approved reports with unresolved dependencies/limitations appeared clean; rendered audit could disagree with the state machine. | Emit `COMPLETED_WITH_LIMITATIONS` when appropriate, render effective decisions and dependencies, return nonzero from run/resume unless cleanly completed. |
| Budget boundaries | First LLM call bypassed project cap; paid search bypassed preflight. Invalid numeric configuration could silently become defaults. | Gate first call and each search against both caps; validate numeric settings; check cancellation/runtime between requests and tools. Budgets remain estimates, not billing guarantees. |
| Persistence | Counter updates could survive without their transition; stale ledger instances overwrote spend; corruption reset accounting. | Transactional state/counter/event update with expected-state check; file locking and reload on ledger writes; fail closed on corruption. Reconcile interrupted SQLite/ledger writes using the greater retained total. Serialize runs sharing a projects root. |
| Fetch security/resources | Auditor could fetch non-HTTP URLs; redirects could reach local targets; page reads were unbounded. | Validate public HTTP(S) URLs and redirects, reject private/local addresses and userinfo, restrict ports, cap reads at 2 MB. Network egress policy is still required against DNS rebinding. |
| Artifact/computation security | Real artifact writers did not use path confinement; predictable temp symlinks and enormous arithmetic could escape intended boundaries. | Enforce realpath confinement, use unique temporary files, bound AST size and exponentiation, reject sequence arithmetic. Authorization gates remain intact; generated code stays disabled. |
| Live checks | Smoke command could spend without an explicit flag and mark Tavily valid after a fallback; legacy live test used a fixed model. | Require explicit paid authorization for smoke/full validation; smoke calls Tavily directly and records search charges. New bounded runner takes an explicitly selected model and prices. |

## Verification

Run from the existing checkout with its configured environment:

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m pip check
git diff --check
```

Final validation: **142 passed, 1 skipped**; `pip check` reports no broken
requirements and `git diff --check` passes. The single
skipped test is the opt-in live API test. No paid calls were authorized or made
in this audit. Previous local connectivity and the two failed live executions
are user-reported history, not evidence of a successful run of this revision.

`tests/test_workflow_e2e.py` uses the real provider adapter, search/retrieval
adapters, calculator, state machine, SQLite, ledger and report renderer, with
only SDK/HTTP/DNS transports mocked. It asserts:

1. Evaluator requests a specific prompt revision and creator incorporates it.
2. Native search runs and its returned evidence reaches the next executor turn.
3. Executor fetches the cited page and submits a report with an omitted fee.
4. Auditor independently refetches it, checks the material claim and requests correction.
5. Correction receives the prior report and issue, calls calculate, and changes 12 to 10.
6. A new independent audit explicitly resolves the original issue.
7. Final artifacts, effective audit, status, spend, tools and events agree.
8. A timeout after search resumes with its stored result, including after reopening SQLite;
   terminal resume makes no further calls.

The bounded live command itself is also exercised with mocked transports.
`tests/test_audit_regressions.py` covers the defects above. Older static adversarial
fixtures that keep returning an unchanged bad report and then silently omit
issues now correctly expect limitations instead of clean approval. The correction
happy-path fixture explicitly resolves its issue. Offline CLI tests mock child
process transports too; they do not scrape external services.

## Remaining limitations and defects

- **Live integration unverified:** model availability, actual strict schemas,
  reasoning-item continuations, search access and research quality still require
  the authorized run in LIVE_VALIDATION.md. The earlier two failures have offline
  regression coverage, not a successful live retest.
- **Research judgement is fallible:** passage presence does not establish semantic
  entailment. The auditor has independent text but remains an LLM; source
  completeness, contradictions outside fetched context and uncited narrative can
  still be missed. Verification covers at most the configured source cap and
  fetched text is truncated. No production accuracy guarantee follows.
- **Billing uncertainty:** rates are operator-configured estimates; character-based
  input estimates are approximate. A provider can bill a timed-out request whose
  usage never arrived. A crash between a remote response and its local checkpoint
  can repeat a call or lose that call's usage. Server-side account limits and bill
  reconciliation are still necessary for a strict monetary ceiling. Spend recovery
  covers the local database/ledger split, not unknowable remote charges.
- **Legacy resume granularity:** clients without native tool support still checkpoint
  at the completed execution step, not each tool turn. Native checkpoints do not
  make remote side effects exactly once. Default tools remain read-only.
- **Networking:** DNS validation has a resolution/connection race and is not a network
  sandbox. Enforce egress restrictions for untrusted research, especially on local
  machines. DNS/proxy-only name resolution can fail closed for otherwise public
  sources. Captchas, paywalls, PDFs and JavaScript-only pages remain unsupported.
- **Runtime/platform:** Linux/macOS file locking serializes a shared projects root.
  Multiple roots share no aggregate cap. Generic custom tool `timeout_s` metadata
  is not a hard process timeout; built-in HTTP requests use fixed 30s socket
  timeouts and computation has resource guards. A blocking request cannot be
  cancelled mid-flight. Project runtime includes idle time since creation.
- **Historical data:** prior CC ids are not migrated to new stable identities;
  historical terminal projects are not rewritten. Keep old artifacts as evidence
  and start a fresh bounded live project for this revision.

## Delivery

See LIVE_VALIDATION.md for exact bounded commands using existing local credentials.
No environment reinstall is required. GitHub API network access is needed to open
the requested pull request; Git access and API access have different scopes.
