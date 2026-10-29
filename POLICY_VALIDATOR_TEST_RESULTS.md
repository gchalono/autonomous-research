# Policy-validator tests — V6

**Final offline result: 284 passed, 2 pricing-evidence cases skipped/BLOCKED, 1 paid live test deselected; 0 failures.** Runtime: 6.75 seconds. No paid execution or production allowance activation occurred.

## Original V5 cases

Before any production edit:

```bash
.venv/bin/python -m pytest policy_v5/test_policy_validation.py -q -ra -k 'P01 or P15 or Q01'
```

`policy_v6/baseline/original_four.log`: **2 failed, 2 skipped, 13 deselected**, 0.06 seconds. The Q01 unknown-field and unsupported-version assertions both failed because no exception was raised. P01/P15 remained blocked by missing official pricing/contracts, not code errors.

After repair:

```bash
.venv/bin/python -m pytest policy_v5/test_policy_validation.py --policy-audit-output policy_v6/original_cases -q -ra -k 'P01 or P15 or Q01'
```

`policy_v6/original_four_retest.log`: **2 passed, 2 skipped/BLOCKED, 13 deselected**, 0.03 seconds. Both Q01 conditions now reject before guard use. P01/P15 still do not assert genuine current pricing from synthetic data. Their original test function bodies are unchanged; `policy_v6/original_case_integrity.json` confirms this, and originals are preserved in the baseline directory.

The remaining V5 targeted cases also pass in the final combined run: **15 passed, 2 external blocks**. The missing-price fixture now expects rejection at the actual loader rather than waiting for dispatch; no transport can be reached. This is earlier fail-closed behavior, not a relaxed assertion.

## New independent validator cases

Initial targeted command:

```bash
.venv/bin/python -m pytest policy_v6/test_v6_validator.py -q -ra
```

The initial 60 cases passed in 0.15 seconds (`policy_v6/validator_tests.log`). Two additional enforcement checks were subsequently added for a lower policy budget and a search-unit limit inside an over-reserved monetary amount. The final combined run executed **all 62 V6 cases successfully**; `policy_v6/validator_results.json` and per-case JSON contain their final outcomes and observations.

| ID | Cases / expected behavior | Final result |
|---|---|---|
| V01 | Supported complete version accepted without ledger creation | PASS |
| V02 | Future, malformed, boolean, float, string or null version rejected | PASS, 7 variants |
| V03 | Missing version rejected, no default | PASS |
| V04 | Unknown root field rejected | PASS |
| V05 | Unknown model/search/reference nested field rejected | PASS, 3 variants |
| V06 | Misspelled safety constraint rejected | PASS |
| V07 | Missing required budget rejected | PASS |
| V08 | Strict field types; no bool/int or string/int coercion | PASS, 5 variants |
| V09 | Negative, zero, nonfinite, malformed or above-$1 budget rejected | PASS, 6 variants |
| V10 | Wrong precision rejected; only integer 6 supported | PASS, 5 variants |
| V11 | Contradictory budget/individual/aggregate or operation maxima rejected | PASS, 3 invalid variants |
| V11b / V11c | Individual cap and $0.90 aggregate cap actually enforced; separate $0.50 policy budget cannot expand to global $1 | PASS, 2 enforcement cases |
| V12 | Unsupported retries, concurrency and call-count constraints rejected | PASS, 5 variants |
| V13 | Unapproved model, client operation and endpoint option produce zero sends | PASS |
| V14 | Missing/nonfinite/zero/binary-float price or unverified declaration rejected | PASS, 6 variants |
| V14b | Applicable reference required; declared search maximum must cover units × price | PASS |
| V14c | Excess credits freeze even when cost fits an over-reserved dollar amount | PASS |
| V15 | Malformed, duplicate-field, wrong-root and nonfinite JSON rejected | PASS, 4 variants |
| V16 | Invalid actual production policy file: no default/fallback and zero dispatch | PASS |
| V17 | Invalid mutated programmatic policy: adapter, exposed client and search helper all produce zero dispatch | PASS |
| V18 | Legacy format rejected; explicit reviewed test migration accepted without activation | PASS |
| V19 | Schema-only draft inspection succeeds; usable guard/initializer reject; production paths remain absent | PASS |
| V20 | Missing/corrupt/version-incompatible/draft policy during authorization: zero dispatch | PASS, 4 variants |

These tests use a separately authored version-1 fixture, not the legacy fixture-migration helper. `VERIFIED_OFFICIAL` declarations and source URLs inside synthetic fixtures are simulated review metadata; no actual provider prices are certified by these tests. All billable transports are mocked. Test-local INET socket connects are prohibited.

## Complete offline regression

Final command:

```bash
.venv/bin/python -m pytest tests audit_v3/test_independent_guard.py audit_v4/test_v4_adversarial.py audit_v4/test_v4_review.py policy_v5/test_policy_validation.py policy_v6/test_v6_validator.py --audit-output policy_v6/final/v3 --policy-audit-output policy_v6/final -q -ra -k 'not test_live_end_to_end' -o faulthandler_timeout=20
git diff --check
```

`policy_v6/full_regression.log`: **284 passed, 2 skipped, 1 deselected**, 6.75 seconds. Whitespace check passed.

| Suite | Passed | Evidence-blocked | Paid test excluded |
|---|---:|---:|---:|
| Existing `tests/` including spending guard | 131 | 0 | 1 |
| Existing V3 independent audit | 21 | 0 | 0 |
| Existing V4 adversarial/review | 55 | 0 | 0 |
| V5 policy validation | 15 | 2 | 0 |
| New V6 validator suite | 62 | 0 | 0 |
| **Total** | **284** | **2** | **1** |

No previously failing offline scenario was excluded to obtain this result. The prior 207-pass claim was used as a baseline reference only; all those cases were re-executed. Existing planning, evaluation, mocked search/evidence, corrections, checkpoint and report-generation tests remain passing. No material validator defect or application regression remains observed within the supported contract. This is not formal verification or paid integration/research-quality validation.

## Intermediate failures and investigated environment limitation

The first broader run recorded legacy expectation failures while the new eager loader rejected incomplete fixtures earlier. Review-expiry errors were made explicit; affected fixtures now assert loader rejection and no ledger/transport instead of expecting a later error. The earlier traces/logs remain in `policy_v6/initial_regression.log`, `guard_regression.log` and `targeted_and_core.log`.

That first run also stalled in the **existing A05 async-to-thread test** and was interrupted rather than reported as passing. A diagnostic invocation with `faulthandler_timeout=10` showed worker threads idle after completion while asyncio waited in its selector. A minimal local socketpair test reproduced **PermissionError, errno 1, on AF_UNIX socket.send**, the wakeup used by asyncio thread callbacks. The same standalone asyncio-to-thread example timed out under the sandbox. This is a local IPC/runtime restriction, not a provider connectivity error or validator-lock failure.

Evidence: `policy_v6/concurrency_diagnosis_2.log` (all-thread stack), `policy_v6/local_wakeup_diagnosis.json` and `concurrency_retest.log`. The first diagnostic command also exposed a test-option registration mistake; its usage error is preserved in `concurrency_diagnosis.log`. It was corrected by including the module that registers the option.

The compatibility correction adds a **test-only 10ms loop timer heartbeat** so queued thread callbacks and executor shutdown are processed despite the denied self-wakeup socket. It enables no network route, changes no environment setting, removes no async calls and preserves every monetary assertion. Isolated A05 then passed; the final complete suite including A05 passed. No production async subsystem was altered.

## Fixture migration and preservation

`tests/policy_fixtures.py` explicitly migrates old **synthetic** policy builders to version 1, converts intended float price values to exact decimal strings, and supplies complete simulated review metadata and explicit constraints. It is never imported by production code. Old fixture/source copies exist in `policy_v6/baseline/`. Incomplete/invalid fixtures are rejected earlier; safe legacy production configurations are documented for explicit review/migration, not automatically activated.

Retest plugins now support isolated output directories so historical artifacts are not overwritten by further final runs. All assertions and compatibility changes are reviewable in `policy_v6/v6_source_changes.patch`.

## No-spending and draft evidence

`policy_v6/draft_acceptance.json` records schema/enforcement validity, incomplete pricing, no activation authorization and absent production policy/ledger. Existing draft JSON and identity were updated only for schema compatibility. No unverified price was added.

Only temporary synthetic ledgers were initialized by offline fixtures; no production canonical allowance was created. Real network transports were not used in these tests, no provider credentials were changed, no provider account/billing setting was accessed or modified, and no paid endpoint was probed. No deployment, commit or push occurred.

## Remaining blockers

The validator is ready. Pricing and live readiness remain NO until official exact-model/input/output/context and Tavily credit/account-rate evidence is supplied and reviewed, a usable canonical policy is completed, service permissions are established, and activation/paid execution is separately authorized. The exact responsible-party table is in `POLICY_VALIDATOR_REPAIR.md`. An application policy is not a provider invoice cap and does not constrain unrelated account activity.
