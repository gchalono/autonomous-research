# V16.1 DuckDuckGo parser CPU-exhaustion remediation

## 1–2. Executive summary, baseline and isolation
Implemented and tested, not committed/pushed or independently reviewed. Required baseline 35e45274a9f3b8c7c54d757081bf92ee1d714d8e verified as a local commit. Worktree /workspace/scratch/v16-worktree created with detached HEAD from exactly that object, not by advancing/resetting the shared branch. Target context policy-validator-repair; original shared checkout remains on its earlier local branch/HEAD with its V15 uncommitted files untouched. No live remote contact during V16. Detached worktree is the actual V16 implementation location. No commit, push, merge, rebase, permissions/dependency/policy changes or deployment.

Only src/tools/search.py production modified. Added tests/ddg_v16_fixtures.py, tests/test_ddg_parser.py and this report. Primary working-tree status and all 569 unrelated artifacts compared by full content/name/link/directory inventory; unchanged. Initial W tracked hashes recorded in /workspace/scratch/v16-evidence/baseline-hashes.json. All other tracked bytes equal the baseline, including entire safe_http.py/retrieval.py, provider/executor/financial code. New worktree avoids concurrent shared-source edits; no locks removed or other process terminated.

## 3. Original defect reproduction (actual measured evidence)
Baseline production _search_duckduckgo loaded from baseline-search.py, byte-verified against Git object at the required commit. Only read_public_url replaced by finite fixture bytes. No DNS/HTTP/provider call; fixtures built outside timed regions. First family with repeated CLOSED title anchors and missing snippets showed ~8x CPU per doubling (cubic-like growth), stronger than prior audit's simpler quadratic case. 4KiB ~0.036s, 8KiB ~0.276s, 16KiB ~2.112s. Its 32KiB subprocess hit a bounded 90s timeout across warmup/repeated/traced calls; no completion asserted. Further baseline runs for that family capped at 16KiB. Initial failure retained in before.log and baseline-timeout.json. No intentional 1MiB/24-second historical case replay.

Repeated unclosed anchors independently reproduce approximately quadratic scaling at resource-safe 4–64KiB sizes. Malformed repeated href openings also exhibit quadratic-like doubling. Other controls and all final values below are actual local measurements, not copied prior audit numbers. No formal degree inferred solely from finite ratios.

## 4. Actual production contract and transport
Tool web_search → nonempty query/max_results integer → Tavily if key present, otherwise DuckDuckGo only when no key. SpendingBlocked propagates; no search-provider fallback when Tavily key exists. Those selection/error/billing functions remain byte-identical. DuckDuckGo fixed https://html.duckduckgo.com/html/?q=<urlencode> uses read_public_url, verified at source: V13 public-IP/DNS/pinned connection/TLS/redirect/proxy checks and V14 encoded1MiB /decoded4MiB /HTTP2MiB shared budget (+documented overflow probes) apply. No separate retrieval client or transport introduced. Header wire/decompression limits remain in unchanged safe_http.py.

Results are discovery title/URL/snippet dictionaries, in document order; requested default8, model envelope1..50. Old regex requires an explicit snippet element, but permits empty title/snippet strings; new parser retains that. Existing duplicates preserved; no dedup/reordering. Title and snippet decode entities and inline text; snippet still capped500. New title cap1024 and URL cap4096 bound output state. Missing results/failures return honest unavailable ToolResult; no fabricated result. Search provenance shape result_count/result_urls unchanged. Search results alone are not retrieved source evidence: executor must use protected fetch_page and existing verification/citation controls; none altered.

Legacy /l/?uddg unwrapping, parse_qs then unquote (double percent decode), case-sensitive startswith('http') filtering and duplicate behavior preserved. Prefix filtering is NOT proof of absolute/public/safe URLs. Legacy double decoding can yield spaces; protected source retrieval independently rejects unsafe URL syntax/destinations. HTML-encoded attributes are now decoded as HTML: &amp; in a direct href becomes &, an intentional correctness extension; no extra request. Query-field parsing bounded64 and href4096. No new URL trust claim. Invalid direct limits0/>50/bool reject before fetch, aligning the existing model envelope; not unlimited direct API behavior.

## 5. Design and result-record state machine
States outside → title → awaiting snippet → snippet → complete (append) → outside; rejection/reset clears URL/text/anchor/state. One candidate only; no unmatched-opening queue. Reuse V15 _tag and literal raw-end patterns unchanged as bounded lexical primitives. Tags/names <=8192/64 chars; quote-aware attributes parsed by a second forward scan, retaining only class/href. No DOM/attribute list. HTMLParser was evaluated (htmlparser-inspection.txt): pending-input/attribute construction/grammar are unnecessary here, and association needs a separate state machine anyway; no automatic claim of HTMLParser safety or new dependency.

Explicit div/article/li/tr class-token 'result' scopes define records. Title's result__title h2/h3 wrapper is skipped for effective parent identity; snippet must belong to the same record AND same effective component parent. Thus an irrelevant child subtree cannot provide a snippet. Nested record start clears the outer candidate; no candidate restoration. Multiple titles before a snippet in one explicit record make it ambiguous and reject it; bounded active record-ID set prevents revival. Sibling same-name containers have distinct IDs, not textual-name equivalence.

Legacy containerless fixtures are accepted only as adjacent title/snippet anchor pairs, separated by whitespace/comments and recognized title-wrapper closing syntax. New flat title replaces incomplete earlier candidate with fresh fields; irrelevant markup/non-whitespace/unmatched closure breaks adjacency. Nested/unclosed anchors discard old candidate and resynchronize to a new title. A single anchor with both roles is rejected. A snippet without its own closed title/link is ignored. Extra snippets cannot reuse an already emitted title. Explicit empty snippet elements are valid; missing ones are never invented. A result is appended only after closing its own snippet anchor. Once requested count reached, stop on complete records; the full HTTP body was already safely fetched and bounded, so stopping cannot bypass transport protections.

## 6–7. Complexity and memory
Input cursor strictly forward. Marker/raw-end searches use fixed character/literal patterns. Comments search one consumed suffix. Each lexical tag is consumed and at most8192 chars, then its attributes scanned once more. Entity references have constant maximum35 chars; no unbounded integer conversion/backtracking entity grammar. No substring copy of large whitespace gaps. Structure stack max128; matching closures scan only that bounded stack; record IDs subset of active record ancestors (max128). No recursion. Text append/join clips to title1024/snippet500, without quadratic concatenation. Encoded/decoded HTTP input already bounded4MiB; direct parser enforces4MiB character maximum too.

Current candidate1; at most50 retained complete results; URL<=4096, title<=1024, snippet<=500. Temporary attribute text<=8192 and at most64 class tokens. Test-only instrumentation tracks live buffer identities; initial observation found completed candidate buffers held in a loop-local c, then actual production retention was removed via del c (no assertion weakened). Current instrumented cases show <=4 live buffers, stack<=128, record-ID set<=128; result values are strings, not collectors/DOMs. Logical retained state bounded independently of discarded candidate count. Python container/native overhead and total RSS are not exact quotas.

Actual source-level argument plus geometric benchmarks support approximately O(N) or bounded early rejection. This is not a formal proof of every CPython regex/native path. Fixed lexical limits and finite output prevent practical suffix amplification; no equivalent reachable quadratic path identified in new code. Reuse of private V15 helpers is an explicit coupling: future modifications require joint regressions.

At full production 4MiB input, after measurements cover unmatched openings, unclosed anchors, malformed tags, near classes, whitespace and benign control. Wide-Unicode 4MiB byte input measured separately, producing about20MiB traced peak during UTF-8 widening. Tracemalloc excludes prebuilt fixture storage and native allocations; no process-RSS ceiling claimed. Ordinary ASCII peaks ~4MiB plus bounded parser/output. All observed final peaks <24MiB, a documented measured practical bound for this corpus, not universal allocator enforcement.

## 8. Semantic compatibility corpus
No authentic previously captured DDG HTML available; all fixtures synthetic, never fetched live. Twelve cases created/executed BEFORE source replacement, then exact same HTML/limits replayed afterwards. Baseline/new/difference/intent/contract flags retained in semantics-comparison.json. All twelve outputs match, including order, duplicates, empty explicit fields, inline formatting and legacy double-unwrapped URL. Container/body/wrapper form is structurally modeled, not claimed browser-complete or verified real-site compatibility. Additional valid extension: mixed-case tag/attribute spelling, class-token sets/order, quoted/unquoted attribute variants and HTML href-entity decoding; baseline exact-regex omissions corrected deliberately. Malformed cross-record association behavior intentionally differs for safety.

| Case | Exact baseline/new match | Output count |
|---|---|---:|
| single | True | 1 |
| multiple | True | 2 |
| zero | True | 0 |
| fewer | True | 1 |
| more | True | 1 |
| entities | True | 1 |
| outbound | True | 1 |
| empty_content | True | 1 |
| inline | True | 1 |
| unicode | True | 1 |
| duplicates | True | 2 |
| intervening | True | 1 |

## 9. Adversarial correctness and association
51 new pytest cases cover D01–D20, dedicated A-title/B-snippet, A-URL/B-title, malformed-candidate/later-valid and irrelevant-subtree contamination probes. Scoped two-title ambiguity, nested anchors, comments/scripts/styles, duplicate role/attribute classes, max depth/tag/href/output caps, null/Unicode, missing/extra snippets and 4MiB input tested. Randomized malformed composition seed20261029:50 iterations of10 blocks; every emitted triple must belong to a constructed complete record, never a cross-product. Deterministic cases remain primary evidence, random tests supplementary. All assertions operate on production _search_duckduckgo through read_public_url stubs, not only helpers. Tests never weaken spending/transport.

Operation instrumentation /workspace/scratch/v16-evidence/instrument.py uses runtime wrappers only, no source rewrite. Counts tag spans/calls, fixed-search examined prefixes, buffer constructions/live weak references, reset calls, stack/record maxima and output count. They are logical span/call upper-bound indicators, not native regex-engine character or CPU-instruction counts. Twenty cases across four families/sizes; tag-span totals<=input size and all structural bounds verified. Operations.json binds measurements to final source SHA-256.

## 10. Exact before/after scaling
Benchmark protocol: production fallback with network read stub, finite deterministic fixture generators, one warmup/pilot, three calibrated batches targeting40ms each (CPU accounting can be coarse), medians and min/max ranges for process_time/perf_counter. Separate single untimed tracemalloc peak per fixture (not a fabricated memory median). Fixture generation/import setup excluded from timed regions; UTF-8 decode and query construction included. Subprocesses use credential-free socket-blocked environment, 90s wall/CPU,512MiB AS. Initial stronger baseline32KiB timeout retained and not counted as completion. Superseded development after-source measurements kept outside final table; final49 after records explicitly match final source SHA-256. Baseline29 complete records correspond to unchanged saved Git-verified baseline source. No final table uses mixed source states.

Commands:
```bash
python /workspace/scratch/v16-evidence/run_benchmarks.py before
python /workspace/scratch/v16-evidence/run_benchmarks.py after
/workspace/autonomous-research/.venv/bin/python /workspace/scratch/v16-evidence/benchmark_one.py after wideunicode 4194304 /workspace/scratch/v16-evidence/benchmarks/after_wideunicode_4194304.json
/workspace/autonomous-research/.venv/bin/python /workspace/scratch/v16-evidence/instrument.py
```
The first initial baseline driver run/time-out is before.log; bounded continuation before-bounded.log. Final source-attested continuation after-source-attested.log plus raw JSON source hashes establish final code identity. Unchanged completed baseline rows reused, not remeasured unnecessarily. Each raw JSON records platform/Python, raw bytes/chars, candidate openings, output count/status, CPU/wall medians/ranges, iterations, peak memory. Larger original sizes marked NOT RUN; no extrapolated CPU presented as a measurement.

| Family | Bytes | Original CPU median s | V16 CPU median s | Original peak Python bytes | V16 peak Python bytes | V16 result |
|---|---:|---:|---:|---:|---:|---|
| openings | 2048 | 0.004399418 | NOT RUN | 3762 | NOT RUN | NOT RUN |
| openings | 4096 | 0.036001156 | 0.001280077 | 5810 | 7851 | ValueError |
| openings | 8192 | 0.275942054 | 0.003105173 | 9906 | 11394 | completed |
| openings | 16384 | 2.111999330 | 0.007198254 | 18098 | 20187 | ValueError |
| openings | 32768 | NOT RUN | 0.016988489 | NOT RUN | 36603 | ValueError |
| openings | 65536 | NOT RUN | 0.022001632 | NOT RUN | 69419 | ValueError |
| openings | 262144 | NOT RUN | 0.095899665 | NOT RUN | 266059 | ValueError |
| openings | 1048576 | NOT RUN | 0.288004192 | NOT RUN | 1052319 | completed |
| openings | 4194304 | NOT RUN | 1.145059368 | NOT RUN | 4198219 | ValueError |
| missing_close | 4096 | 0.001500061 | 0.001081033 | 5810 | 7589 | ValueError |
| missing_close | 8192 | 0.006285981 | 0.002284355 | 9906 | 11685 | ValueError |
| missing_close | 16384 | 0.026001691 | 0.004400180 | 18098 | 19909 | ValueError |
| missing_close | 32768 | 0.100007354 | 0.008000450 | 34482 | 36309 | ValueError |
| missing_close | 65536 | 0.395988919 | 0.017334177 | 67250 | 68580 | completed |
| missing_close | 262144 | NOT RUN | 0.068001136 | NOT RUN | 265797 | ValueError |
| missing_close | 1048576 | NOT RUN | 0.271978192 | NOT RUN | 1052229 | ValueError |
| missing_close | 4194304 | NOT RUN | 1.090523037 | NOT RUN | 4197957 | ValueError |
| near_class | 4096 | 0.000004800 | 0.001000059 | 4716 | 7644 | ValueError |
| near_class | 8192 | 0.000009170 | 0.001999998 | 8812 | 11740 | ValueError |
| near_class | 16384 | 0.000014308 | 0.004000595 | 17004 | 19964 | ValueError |
| near_class | 32768 | 0.000023791 | 0.007200430 | 33388 | 36364 | ValueError |
| near_class | 65536 | 0.000044869 | 0.016000731 | 66156 | 69188 | ValueError |
| near_class | 262144 | NOT RUN | 0.064001265 | NOT RUN | 265852 | ValueError |
| near_class | 1048576 | NOT RUN | 0.248002095 | NOT RUN | 1052284 | ValueError |
| near_class | 4194304 | NOT RUN | 0.988067836 | NOT RUN | 4198012 | ValueError |
| malformed | 4096 | 0.000302573 | 0.000006756 | 5810 | 6855 | ValueError |
| malformed | 8192 | 0.001183146 | 0.000007071 | 9906 | 10951 | ValueError |
| malformed | 16384 | 0.004444806 | 0.000009819 | 18098 | 19175 | ValueError |
| malformed | 32768 | 0.018000546 | 0.000010346 | 34482 | 35559 | ValueError |
| malformed | 65536 | 0.068003453 | 0.000011853 | 67250 | 68327 | ValueError |
| malformed | 262144 | NOT RUN | 0.000032304 | NOT RUN | 264935 | ValueError |
| malformed | 1048576 | NOT RUN | 0.000111910 | NOT RUN | 1051367 | ValueError |
| malformed | 4194304 | NOT RUN | 0.000394448 | NOT RUN | 4197095 | ValueError |
| whitespace | 4096 | 0.000004864 | 0.000004874 | 4716 | 5025 | completed |
| whitespace | 8192 | 0.000006536 | 0.000007093 | 8812 | 9121 | completed |
| whitespace | 16384 | 0.000010035 | 0.000010964 | 17004 | 17313 | completed |
| whitespace | 32768 | 0.000017059 | 0.000017193 | 33388 | 33697 | completed |
| whitespace | 65536 | 0.000028987 | 0.000033888 | 66156 | 66465 | completed |
| whitespace | 262144 | NOT RUN | 0.000124960 | NOT RUN | 263073 | completed |
| whitespace | 1048576 | NOT RUN | 0.000500019 | NOT RUN | 1049505 | completed |
| whitespace | 4194304 | NOT RUN | 0.001999972 | NOT RUN | 4195233 | completed |
| benign | 4096 | 0.000069236 | 0.001142957 | 13018 | 14555 | ValueError |
| benign | 8192 | 0.000078777 | 0.001333566 | 18362 | 19547 | completed |
| benign | 16384 | 0.000082195 | 0.001378942 | 26554 | 27739 | completed |
| benign | 32768 | 0.000083920 | 0.001333205 | 42938 | 44123 | completed |
| benign | 65536 | 0.000081635 | 0.001333161 | 75706 | 76891 | completed |
| benign | 262144 | NOT RUN | 0.001333429 | NOT RUN | 273499 | completed |
| benign | 1048576 | NOT RUN | 0.001516924 | NOT RUN | 1059931 | completed |
| benign | 4194304 | NOT RUN | 0.001818093 | NOT RUN | 4205659 | completed |
| wideunicode | 4194304 | NOT RUN | 0.004000498 | NOT RUN | 20971705 | completed |

### Adjacent growth ratios

- openings before: 2048→4096: input×2, CPU×8.183; 4096→8192: input×2, CPU×7.665; 8192→16384: input×2, CPU×7.654.
- openings after: 4096→8192: input×2, CPU×2.426; 8192→16384: input×2, CPU×2.318; 16384→32768: input×2, CPU×2.360; 32768→65536: input×2, CPU×1.295; 65536→262144: input×4, CPU×4.359; 262144→1048576: input×4, CPU×3.003; 1048576→4194304: input×4, CPU×3.976.
- missing_close before: 4096→8192: input×2, CPU×4.190; 8192→16384: input×2, CPU×4.136; 16384→32768: input×2, CPU×3.846; 32768→65536: input×2, CPU×3.960.
- missing_close after: 4096→8192: input×2, CPU×2.113; 8192→16384: input×2, CPU×1.926; 16384→32768: input×2, CPU×1.818; 32768→65536: input×2, CPU×2.167; 65536→262144: input×4, CPU×3.923; 262144→1048576: input×4, CPU×4.000; 1048576→4194304: input×4, CPU×4.010.
- near_class before: 4096→8192: input×2, CPU×1.910; 8192→16384: input×2, CPU×1.560; 16384→32768: input×2, CPU×1.663; 32768→65536: input×2, CPU×1.886.
- near_class after: 4096→8192: input×2, CPU×2.000; 8192→16384: input×2, CPU×2.000; 16384→32768: input×2, CPU×1.800; 32768→65536: input×2, CPU×2.222; 65536→262144: input×4, CPU×4.000; 262144→1048576: input×4, CPU×3.875; 1048576→4194304: input×4, CPU×3.984.
- malformed before: 4096→8192: input×2, CPU×3.910; 8192→16384: input×2, CPU×3.757; 16384→32768: input×2, CPU×4.050; 32768→65536: input×2, CPU×3.778.
- malformed after: 4096→8192: input×2, CPU×1.047; 8192→16384: input×2, CPU×1.389; 16384→32768: input×2, CPU×1.054; 32768→65536: input×2, CPU×1.146; 65536→262144: input×4, CPU×2.725; 262144→1048576: input×4, CPU×3.464; 1048576→4194304: input×4, CPU×3.525.
- whitespace before: 4096→8192: input×2, CPU×1.344; 8192→16384: input×2, CPU×1.535; 16384→32768: input×2, CPU×1.700; 32768→65536: input×2, CPU×1.699.
- whitespace after: 4096→8192: input×2, CPU×1.455; 8192→16384: input×2, CPU×1.546; 16384→32768: input×2, CPU×1.568; 32768→65536: input×2, CPU×1.971; 65536→262144: input×4, CPU×3.687; 262144→1048576: input×4, CPU×4.001; 1048576→4194304: input×4, CPU×4.000.
- benign before: 4096→8192: input×2, CPU×1.138; 8192→16384: input×2, CPU×1.043; 16384→32768: input×2, CPU×1.021; 32768→65536: input×2, CPU×0.973.
- benign after: 4096→8192: input×2, CPU×1.167; 8192→16384: input×2, CPU×1.034; 16384→32768: input×2, CPU×0.967; 32768→65536: input×2, CPU×1.000; 65536→262144: input×4, CPU×1.000; 262144→1048576: input×4, CPU×1.138; 1048576→4194304: input×4, CPU×1.199.

Interpretation: repeated closed titles/no snippet show cubic-like baseline growth; missing-close and malformed-href families show approximately quadratic baseline growth. New scans show approximately proportional growth or early rejection over the tested geometric range. Malformed truncations may reject instead of complete; status is recorded, never silently treated as successful parse. Benign output stops after50 complete records so input decode increasingly dominates; this is bounded early completion, not a claim every character is parsed. No formal asymptotic proof inferred from finite timings. Output contract and association assertions complement timings.

## 11–13. Protected invariants, search/spending and full offline regressions
Every baseline tracked byte other than search.py unchanged. In search.py, _NoRedirect, _open_tavily, _search_tavily and web_search_tool compared as exact original source segments: byte-identical. No Tavily request, include_usage, billing unit, guard, fallback selection, provider retries or provenance/approval behavior change. V13/V14 safe_http.py and V15 retrieval.py byte-identical; all corresponding suites pass unchanged. Canonical policy draft, no active policy or canonical ledger. No secret/environment/network changes or dependencies.

Fresh full Git archive of exact C baseline overlaid with exact current search.py and new fixture/tests in /workspace/scratch/v16-evidence/tree. Snapshot hashes before/after match. Existing V6-compatible offline child/network guard copied byte-exact from independently approved V15 audit bundle into harness/; only external runner args/source snapshot are V16-specific, no assertions/security checks weakened. Credentials stripped; actual socket/DNS/sendto denied; shared checkout and snapshot source/canonical writes denied. Only V6 native evidence JSON writable in test source tree, other configured evidence under disposable workspace. Test copies contain no 569 unrelated untracked artifacts. Fresh62 V6 case files/native exit_status0 verified against external census. Source test files unchanged. 90s wall/45s CPU/1GiB AS/16MiB file. Collection/teardown/session completion explicitly checked. Groups overlap and are not summed.

### ddg

```bash
python /workspace/scratch/v16-evidence/run_tests.py ddg tests/test_ddg_parser.py -q -ra -p no:cacheprovider
```
Source cwd /workspace/scratch/v16-evidence/tree, final source identity above/below. Collected 51; selected 51; passed 51; failed 0; skipped 0; xfailed 0; xpassed 0; deselected 0; process/pytest exits0; timeout NO; teardown 51 reports/0 errors; session finalized successfully; collection/internal errors0. Log/census /workspace/scratch/v16-evidence/ddg.log, ddg.json, ddg_summary.json.

### search

```bash
python /workspace/scratch/v16-evidence/run_tests.py search tests/test_tools.py -q -ra -p no:cacheprovider
```
Source cwd /workspace/scratch/v16-evidence/tree, final source identity above/below. Collected 3; selected 3; passed 3; failed 0; skipped 0; xfailed 0; xpassed 0; deselected 0; process/pytest exits0; timeout NO; teardown 3 reports/0 errors; session finalized successfully; collection/internal errors0. Log/census /workspace/scratch/v16-evidence/search.log, search.json, search_summary.json.

### tools

```bash
python /workspace/scratch/v16-evidence/run_tests.py tools tests/test_tools.py tests/test_orchestration.py tests/test_recovery.py tests/test_phase4.py -q -ra -p no:cacheprovider
```
Source cwd /workspace/scratch/v16-evidence/tree, final source identity above/below. Collected 23; selected 23; passed 23; failed 0; skipped 0; xfailed 0; xpassed 0; deselected 0; process/pytest exits0; timeout NO; teardown 23 reports/0 errors; session finalized successfully; collection/internal errors0. Log/census /workspace/scratch/v16-evidence/tools.log, tools.json, tools_summary.json.

### ssrf

```bash
python /workspace/scratch/v16-evidence/run_tests.py ssrf tests/test_ssrf.py -q -ra -p no:cacheprovider
```
Source cwd /workspace/scratch/v16-evidence/tree, final source identity above/below. Collected 54; selected 54; passed 54; failed 0; skipped 0; xfailed 0; xpassed 0; deselected 0; process/pytest exits0; timeout NO; teardown 54 reports/0 errors; session finalized successfully; collection/internal errors0. Log/census /workspace/scratch/v16-evidence/ssrf.log, ssrf.json, ssrf_summary.json.

### bounded

```bash
python /workspace/scratch/v16-evidence/run_tests.py bounded tests/test_bounded_retrieval.py -q -ra -p no:cacheprovider
```
Source cwd /workspace/scratch/v16-evidence/tree, final source identity above/below. Collected 43; selected 43; passed 43; failed 0; skipped 0; xfailed 0; xpassed 0; deselected 0; process/pytest exits0; timeout NO; teardown 43 reports/0 errors; session finalized successfully; collection/internal errors0. Log/census /workspace/scratch/v16-evidence/bounded.log, bounded.json, bounded_summary.json.

### html

```bash
python /workspace/scratch/v16-evidence/run_tests.py html tests/test_html_extraction.py -q -ra -p no:cacheprovider
```
Source cwd /workspace/scratch/v16-evidence/tree, final source identity above/below. Collected 43; selected 43; passed 43; failed 0; skipped 0; xfailed 0; xpassed 0; deselected 0; process/pytest exits0; timeout NO; teardown 43 reports/0 errors; session finalized successfully; collection/internal errors0. Log/census /workspace/scratch/v16-evidence/html.log, html.json, html_summary.json.

### full

```bash
python /workspace/scratch/v16-evidence/run_tests.py full tests audit_v3/test_independent_guard.py audit_v4/test_v4_adversarial.py audit_v4/test_v4_review.py policy_v5/test_policy_validation.py policy_v6/test_v6_validator.py policy_v7/test_v7_policy.py policy_v7/followup/test_blocked_policy.py --audit-output /workspace/scratch/v16-evidence/regression/v3 --policy-audit-output /workspace/scratch/v16-evidence/regression -q -ra -p no:cacheprovider -k 'not test_live_end_to_end'
```
Source cwd /workspace/scratch/v16-evidence/tree, final source identity above/below. Collected 531; selected 530; passed 528; failed 0; skipped 2; xfailed 0; xpassed 0; deselected 1; process/pytest exits0; timeout NO; teardown 530 reports/0 errors; session finalized successfully; collection/internal errors0. Log/census /workspace/scratch/v16-evidence/full.log, full.json, full_summary.json.

Full528 passed,2 historical V5 skips,1 paid live test deselected. Prior477 passing cases/outcomes retained; only gzip-parameter collection timestamps normalized by unchanged function/outcome multiplicity, all other prior nodes compared exactly.51 new passing cases added. No skipped failure or partial-suite substitution.

## 14–15. Exact file inventory and hashes
Modified: src/tools/search.py — bounded stateful parsing only; unchanged trusted-provider/tool bodies.
Added: tests/ddg_v16_fixtures.py — deterministic semantic/adversarial fixture generator.
Added: tests/test_ddg_parser.py —51 correctness, association and resource tests.
Added: V16_DDG_PARSER_REMEDIATION_REPORT.md — this evidence/handoff.
Removed: none. No other tracked change. Index empty, detached HEAD still baseline; no commit/push/ref advance.

- `src/tools/search.py`: `75ba4519d454c8d7e550f9aaf4dca2d5ca343232d1f881c30cd538a5e8dda78c`
- `tests/ddg_v16_fixtures.py`: `8660801e34cc3000e0c1481026a23c6f34c8b2e472a4dd65fec49d870b202c93`
- `tests/test_ddg_parser.py`: `f6d89954b0e9f8e93868d50c513084dccef62ac89516c80779a49cf2dd90df6a`

Final report hash lives in external final-manifest.json and bundle MANIFEST.json (avoiding self-reference). Complete unified diff includes all four paths, saved as /workspace/scratch/v16-evidence/V16_COMPLETE.patch and included in audit bundle.

## 16. Known limitations
Synthetic fixtures only; real captured DuckDuckGo markup compatibility remains unverified, no live page fetched. Strict 8192-tag/64-name/64-class/128-depth/4096-URL limits may reject unusually large valid markup. Unknown/malformed HTML can fail whole parsing rather than return partial discovery results. Containerless records require adjacency; this deliberately refuses old regex's unsafe cross-markup matching. Explicit-record component parent identity is a structural association rule, not semantic understanding of page content. One explicit record permits only its first unambiguous title/snippet; multiple-title ambiguity rejects. Inline text/entity handling follows HTML node boundaries, so references split by tags are not recombined. Href HTML entity decoding fixes a legacy omission; double-unquote/prefix filtering weaknesses otherwise remain as discovery-only behavior, not source-fetch authorization. No hard end-to-end retrieval/CPU deadline or process RSS guarantee. V15 lexical helper coupling requires joint future regression.

Missing hard deadline, V14 IncompleteRead error masking, required-proxy refusal, calculator exhaustion, unsupported claims, zero-citation approval, live TLS/retrieval acceptance, provider entitlement/pricing and deployment readiness remain out of scope. No next remediation begun.

## 17–18. Independent Muse audit and next action
Audit bundle V16_DDG_PARSER_AUDIT_BUNDLE.zip contains baseline identity/runtime/tests/fixtures, exact patch/current sources, semantic corpus and before/new outputs, deterministic seed20261029, raw final benchmarks, timeout record, operation instrumentation, test evidence, dependency/environment info, manifests and portable offline replay. No secrets or unrelated untracked artifacts. New packaging runner may adapt paths/group names but preserves the established offline guard/census unchanged. No commit/push transfer is authorized.

Independent plan: verify manifest/patch/current source identity; run baseline safely (closed-title family <=16KiB, others<=64KiB; do not rerun the timed-out32KiB case), compare final before/after ratios/statuses and cap memory. Inspect cursor advancement/attributes/entity work, bounded candidate/stack/buffer state and every cross-result association path. Reproduce synthetic semantics; separately obtain captured-site fixtures only with future authorization. Run new/old/full offline gates with preserved assertions and inspect native evidence/session exits. Check protected source hashes, Tavily/guard identity and primary artifact preservation. No claim Muse already reviewed V16.

Next action: independent Muse audit of this uncommitted V16 state machine, association rules and scaling evidence.

### Audit-package replay verification

Extracted ZIP replay independently passed DDG51 and full528/2skip/1paid-deselected using only the bundled baseline/runtime/fixtures, no external checkout. Teardown/session completion checked. Portable benchmark child before/after4KiB and portable20-case operation instrumentation also executed successfully against the patch-reconstructed bundled source. Bundle-replay logs/census and smoke JSON retained separately.
