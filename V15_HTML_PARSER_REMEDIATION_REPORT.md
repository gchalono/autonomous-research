# V15.1 HTML parser remediation report

## 1. Executive summary
Implemented within the authorized retrieval boundary; ready for independent Muse audit, not independently audited yet. Repeated whole-document backtracking extraction passes were replaced with a forward, bounded-state scanner. Known script/style/title and malformed-tag quadratic paths reproduced before editing; after measurements and structural analysis support bounded approximately linear work or early rejection on the tested families, not a universal formal proof of Python runtime complexity.

All required offline groups pass, including 43 new tests and full regression 477 passed / 2 historical skips / 1 paid test deselected, with successful collection, teardown and session finish. V13/V14 transport and all financial controls remain byte-identical. No commit, push, network/paid call, deployment or allowance activation.

## 2. Baseline and exact source identity
Repository gchalono/autonomous-research; configured origin https://github.com/gchalono/autonomous-research.git; branch policy-validator-repair; required/current HEAD d52378c18342494754b40504b4af51b3cefbcdd7. Initially no tracked/staged changes; 569 unrelated untracked paths preserved. No reset/rebase/reconciliation. Initial full status and tracked hashes: /tmp/v15-evidence/status-before.txt, baseline-hashes.json. Original retrieval snapshot matches git show of the exact baseline.

## 3. Original defect reproduction and benchmark method
Original production fetch_url executed with only read_public_url replaced by finite fixture bytes; no networking, DNS or unrelated setup in timed regions. Six initial families: repeated unclosed script, style, alternating script/style, malformed '<a ' without '>', repeated ordinary opening tags, and benign HTML. Additional repeated-title family independently reproduced another superlinear path in title_match. Fixtures use the same deterministic pattern/truncation in before and after runs. Original tested at 4096/8192/16384/32768 bytes; deliberately no multi-MiB run of known quadratic malicious baseline.

Warm-up, pilot, three calibrated batches; CPU via process_time(), wall via perf_counter(). Batches target ~80ms each to reduce observed coarse (~4ms) CPU accounting granularity despite the advertised nanosecond clock resolution. Report medians per invocation and min/max dispersion, iterations per batch in each JSON. Memory measured in a separate untimed tracemalloc invocation: peak Python allocations, excluding prebuilt fixture string/bytes and native allocations; it is one traced peak per fixture, not a fabricated multi-repetition memory median or process RSS measurement. Decoding and extraction are included. Conditions are same fixtures, code entry, clock method and environment; benchmark subprocess resource ceilings do not affect completed measurements.

Environment: 3.12.14 (main, Aug 25 2026, 14:00:49) [Clang 22.1.3 ]; Linux-6.18.55-x86_64-with-glibc2.41. Actual parser source evaluated, not regex microbenchmarks alone. Calibrated before log /tmp/v15-evidence/before-benchmarks.log; each raw record in benchmarks/. Initial unbatched measurements had zero CPU deltas on short benign cases; they were replaced by calibrated measurements, never treated as reliable ratios.

Commands:
```bash
python /tmp/v15-evidence/run_benchmarks.py before
python /tmp/v15-evidence/run_benchmarks.py after
python /tmp/v15-evidence/finish_benchmarks.py
/workspace/autonomous-research/.venv/bin/python /tmp/v15-evidence/benchmark.py after wideunicode 4194304 /tmp/v15-evidence/benchmarks/after_wideunicode_4194304.json
/workspace/autonomous-research/.venv/bin/python /tmp/v15-evidence/benchmark.py before wideunicode 4194304 /tmp/v15-evidence/benchmarks/before_wideunicode_4194304.json
```
Original driver after run stopped on a 30-second timeout for memory-traced 4MiB repeated ordinary tags; this failure is retained in after-benchmarks.log, not counted as a completion. finish_benchmarks.py retries that known finite fixture with a bounded 90-second wall/CPU allowance, then completes remaining controls/title fixtures. The benchmark child still imposes 512MiB address-space limit. All final referenced records completed. Current original driver retains its conservative 30s timeout, so use finish_benchmarks.py for the documented high-overhead trace case. No genuinely unbounded fixture or uncontrolled worker.

## 4. Root cause
Original script/style substitution '<(script|style)[^>]*>.*?</\1>' retries a missing closing pattern from repeated opening positions. The generic tag-removal regex likewise rescans suffixes when many incomplete '<a ' sequences have no '>'. Title extraction '<title[^>]*>(.*?)</title>' also repeatedly retries absent closers. Subsequent unescape/substitutions make additional full-document copies/scans; all were inspected, not presumed safe. New parser removes all three vulnerable extraction paths and avoids suffix slicing/rescans.

## 5–6. Strategy and evaluated alternatives
HTMLParser was evaluated first: installed source retained in htmlparser-inspection.txt; incomplete-attribute experiment in htmlparser-buffer.json. This installed Python has geometric pending-input protection in feed (so no unsupported claim that every HTMLParser is quadratic). It still stores pending incomplete input and parses/materializes full attribute lists and start-tag text that a text-only extractor does not need; tolerant regex grammar/buffering differs across supported Python versions. A safe adapter would need additional token limits/raw-text/malformed semantics. Chosen alternative is a small bounded scanner, not a browser DOM, JavaScript engine or HTML sanitizer; no dependency added. Chunk-feeding HTMLParser without validating its buffering, retaining old regexes behind only a size cap, worker architecture redesign, and adding a third-party parser were rejected for this narrow scope.

Scanner advances its cursor only forward. Marker searches are fixed character classes or fixed raw closing-tag prefixes; whitespace alternatives are disjoint runs; entity expressions have constant maximum width. Each tag scan is <=8192 chars, each name <=64, and processed spans are consumed rather than retried. No recursive nesting stack, attribute list, full-document lowercased copy or global extraction substitution. The first fixed-character re.search preserves the existing parser-failure fault-injection seam; subsequent marker scans use pos-aware compiled search with no suffix copy. This is not a return to vulnerable patterns.

## 7–8. Changed files and resource contract
Only production file modified: src/tools/retrieval.py. New tests: tests/test_html_extraction.py. New report: V15_HTML_PARSER_REMEDIATION_REPORT.md. No other tracked source/test/config changes.

| Resource | Bound |
|---|---|
| Production decoded bytes | Existing V14 maximum 4194304, unchanged |
| Scanner input characters | <=4194304, checked; production UTF-8 conversion cannot exceed decoded-byte count |
| Pending token buffer | None; scanning directly in the existing immutable string |
| Per-tag processing | <=8192 characters; incomplete/overlong tags fail |
| Name retained | <=64 ASCII name characters |
| Attribute storage | None; quote-aware scan, no attribute list |
| Entity passed to unescape | <=35 characters; no unbounded numeric conversion |
| Suppression / nesting | One script/style enum plus booleans; no stack or recursion |
| Title output | <=1024 characters, accumulated only up to cap |
| Visible output | <=12000 characters, accumulated only up to cap |
| Output list lengths | <= respective character caps; no empty append growth |

Output pieces, joins and normalized whitespace remain bounded, including Unicode. There is no full-document unescape or regex replacement. The existing full HTTP body and UTF-8 decoded input still exist: a mostly ASCII 4MiB body with one non-BMP scalar widens the Python Unicode representation. Measured peak for that decode+parse invocation is about 20MiB; this is not claimed to be parser-state alone. Native allocator/RSS and V14 transport intermediates are outside tracemalloc. Logical parser-owned state is bounded by output caps and fixed token/state limits; measured Python peak remained below a documented practical 24MiB budget for this corpus, excluding prebuilt fixture storage. This is an observed practical bound plus structural state limits, not a cross-platform process memory quota.

## 9–10. Malformed HTML and output semantics
- Ordinary text and title retained, entities decoded and Unicode/replacement characters preserved. All whitespace runs normalize to one space; tags create visible-space boundaries. Existing title remains visible in page text for compatibility. Output is not a DOM rendering and does not implement CSS visibility/layout.
- Script/style names ASCII-case insensitive; their content suppressed until their own valid closing tag or EOF. Nested openings (including other raw tags) do not stack. Self-closing script/style opening syntax still suppresses subsequent raw content, conservatively. Malformed/overlong candidate closers fail; no raw-text fallback leaks script/style data.
- Attribute quoting honored; tag-looking strings inside quoted attributes do not become markup. Tags over 8192 characters, names over 64, embedded unquoted '<', malformed closers and incomplete ordinary opening tags fail retrieval as non-citable. Some legitimate pages with very large attributes therefore refuse; explicit security strictness, not universal browser compatibility.
- Comments ignored; unclosed comments suppress remainder. Declarations/processing instructions skipped under the same bounded token scan. Ordinary '<' comparisons remain text. Comments containing scripts do not start suppression.
- First title wins, even empty; multiple titles never create a stack. Unclosed title retains bounded available text. Nested title openings do not recurse. Ordinary title tag removal does not introduce artificial title-internal spacing; title whitespace normalizes safely. Cap 1024 intentionally changes extreme title behavior.
- Named/numeric references processed once from bounded tokens. Overlong malformed numeric/name references stay literal rather than unbounded integer conversion; decoded '<script>' text is never recursively parsed as markup. Incomplete legacy entities are handled predictably by bounded html.unescape behavior.
- Existing fetch_url returns (title,text); tool TITLE/output/provenance keys and chars length preserved. HTTP failure propagates to ok=false with no provenance and the non-citation warning. V14 overflow never becomes successful partial HTML. Existing final 12000-character readable-text truncation remains separate from HTTP completeness.

Initial prototype tests exposed an entity-semicolon boundary bug and a fault-injection seam mismatch. Production entity logic was corrected; a single safe fixed-character re.search preserved the existing fault-injection boundary. No existing assertion changed, no unsafe semantics retained. development.log records two initial failures; development-fixed.log records all 137 cases passing before final extra memory tests. This is development evidence, not substituted for final regression.

## 11–12. Before/after CPU scaling and peak memory
Raw summary including ranges, wall medians, ratios and platform: /tmp/v15-evidence/scaling-summary.json; individual records in benchmarks/. Ratios are empirical, not mathematical proof. N/A original rows at large sizes mean NOT RUN to avoid known quadratic workload, not zero time.

| Family | Bytes/chars | Original CPU median s | V15 CPU median s | Original traced peak bytes | V15 traced peak bytes | V15 status |
|---|---:|---:|---:|---:|---:|---|
| script | 4096 / 4096 | 0.008000312 | 0.000006649 | 9391 | 6232 | completed |
| script | 8192 / 8192 | 0.034669612 | 0.000009370 | 18127 | 10328 | completed |
| script | 16384 / 16384 | 0.127994161 | 0.000015029 | 36690 | 18520 | completed |
| script | 32768 / 32768 | 0.548002660 | 0.000025354 | 69938 | 34904 | completed |
| script | 262144 / 262144 | NOT RUN | 0.000183923 | NOT RUN | 264280 | completed |
| script | 1048576 / 1048576 | NOT RUN | 0.000693377 | NOT RUN | 1050712 | completed |
| script | 4194304 / 4194304 | NOT RUN | 0.002956837 | NOT RUN | 4196440 | completed |
| style | 4096 / 4096 | 0.009334090 | 0.000008166 | 9967 | 6231 | completed |
| style | 8192 / 8192 | 0.036001970 | 0.000010246 | 19441 | 10327 | completed |
| style | 16384 / 16384 | 0.152026968 | 0.000017131 | 39335 | 18519 | completed |
| style | 32768 / 32768 | 0.604021187 | 0.000030519 | 79356 | 34903 | completed |
| style | 262144 / 262144 | NOT RUN | 0.000206734 | NOT RUN | 264279 | completed |
| style | 1048576 / 1048576 | NOT RUN | 0.000897081 | NOT RUN | 1050711 | completed |
| style | 4194304 / 4194304 | NOT RUN | 0.003385344 | NOT RUN | 4196439 | completed |
| alternating | 4096 / 4096 | 0.008397178 | 0.000008152 | 9967 | 6232 | completed |
| alternating | 8192 / 8192 | 0.036002024 | 0.000013545 | 18211 | 10328 | completed |
| alternating | 16384 / 16384 | 0.135918560 | 0.000017267 | 36875 | 18520 | completed |
| alternating | 32768 / 32768 | 0.572018285 | 0.000035957 | 74371 | 34904 | completed |
| alternating | 262144 / 262144 | NOT RUN | 0.000207228 | NOT RUN | 264280 | completed |
| alternating | 1048576 / 1048576 | NOT RUN | 0.000823461 | NOT RUN | 1050712 | completed |
| alternating | 4194304 / 4194304 | NOT RUN | 0.003111331 | NOT RUN | 4196393 | completed |
| malformed | 4096 / 4096 | 0.003066474 | 0.000003990 | 90041 | 6165 | ValueError |
| malformed | 8192 / 8192 | 0.010500657 | 0.000003829 | 181003 | 10261 | ValueError |
| malformed | 16384 / 16384 | 0.044002234 | 0.000004540 | 363481 | 18485 | ValueError |
| malformed | 32768 / 32768 | 0.160005700 | 0.000007036 | 729931 | 34869 | ValueError |
| malformed | 262144 / 262144 | NOT RUN | 0.000024868 | NOT RUN | 264245 | ValueError |
| malformed | 1048576 / 1048576 | NOT RUN | 0.000092470 | NOT RUN | 1050677 | ValueError |
| malformed | 4194304 / 4194304 | NOT RUN | 0.000417103 | NOT RUN | 4196405 | ValueError |
| openings | 4096 / 4096 | 0.000104386 | 0.002782773 | 16776 | 6534 | completed |
| openings | 8192 / 8192 | 0.000245618 | 0.005428795 | 34121 | 10641 | ValueError |
| openings | 16384 / 16384 | 0.000474596 | 0.011500803 | 69032 | 18869 | completed |
| openings | 32768 / 32768 | 0.000955258 | 0.022999237 | 139625 | 35170 | ValueError |
| openings | 262144 / 262144 | NOT RUN | 0.176002041 | NOT RUN | 264830 | completed |
| openings | 1048576 / 1048576 | NOT RUN | 0.759996716 | NOT RUN | 1051309 | completed |
| openings | 4194304 / 4194304 | NOT RUN | 3.387259348 | NOT RUN | 4196943 | completed |
| benign | 4096 / 4096 | 0.000162685 | 0.001423647 | 33354 | 31377 | completed |
| benign | 8192 / 8192 | 0.000308869 | 0.003172630 | 65102 | 60505 | completed |
| benign | 16384 / 16384 | 0.000604655 | 0.005714905 | 130779 | 120984 | completed |
| benign | 32768 / 32768 | 0.001237056 | 0.008400206 | 262613 | 173849 | completed |
| benign | 262144 / 262144 | NOT RUN | 0.044002513 | NOT RUN | 407497 | completed |
| benign | 1048576 / 1048576 | NOT RUN | 0.167984545 | NOT RUN | 1191542 | completed |
| benign | 4194304 / 4194304 | NOT RUN | 0.696004490 | NOT RUN | 4335774 | completed |
| title | 4096 / 4096 | 0.010500564 | 0.001802617 | 9967 | 6523 | completed |
| title | 8192 / 8192 | 0.044001918 | 0.003407508 | 19441 | 10645 | ValueError |
| title | 16384 / 16384 | 0.167947680 | 0.007000043 | 39335 | 18792 | ValueError |
| title | 32768 / 32768 | 0.751591191 | 0.013295937 | 79356 | 35195 | completed |
| title | 262144 / 262144 | NOT RUN | 0.108005414 | NOT RUN | 264866 | completed |
| wideunicode | 4194304 / 4194301 | 0.088002898 | 0.056003176 | 20971621 | 20971621 | completed |

### Adjacent-size observed ratios

- script before: 4096→8192: size×2, CPU×4.334; 8192→16384: size×2, CPU×3.692; 16384→32768: size×2, CPU×4.281.
- script after: 4096→8192: size×2, CPU×1.409; 8192→16384: size×2, CPU×1.604; 16384→32768: size×2, CPU×1.687; 32768→262144: size×8, CPU×7.254; 262144→1048576: size×4, CPU×3.770; 1048576→4194304: size×4, CPU×4.264.
- style before: 4096→8192: size×2, CPU×3.857; 8192→16384: size×2, CPU×4.223; 16384→32768: size×2, CPU×3.973.
- style after: 4096→8192: size×2, CPU×1.255; 8192→16384: size×2, CPU×1.672; 16384→32768: size×2, CPU×1.781; 32768→262144: size×8, CPU×6.774; 262144→1048576: size×4, CPU×4.339; 1048576→4194304: size×4, CPU×3.774.
- alternating before: 4096→8192: size×2, CPU×4.287; 8192→16384: size×2, CPU×3.775; 16384→32768: size×2, CPU×4.209.
- alternating after: 4096→8192: size×2, CPU×1.662; 8192→16384: size×2, CPU×1.275; 16384→32768: size×2, CPU×2.082; 32768→262144: size×8, CPU×5.763; 262144→1048576: size×4, CPU×3.974; 1048576→4194304: size×4, CPU×3.778.
- malformed before: 4096→8192: size×2, CPU×3.424; 8192→16384: size×2, CPU×4.190; 16384→32768: size×2, CPU×3.636.
- malformed after: 4096→8192: size×2, CPU×0.960; 8192→16384: size×2, CPU×1.186; 16384→32768: size×2, CPU×1.550; 32768→262144: size×8, CPU×3.535; 262144→1048576: size×4, CPU×3.718; 1048576→4194304: size×4, CPU×4.511.
- openings before: 4096→8192: size×2, CPU×2.353; 8192→16384: size×2, CPU×1.932; 16384→32768: size×2, CPU×2.013.
- openings after: 4096→8192: size×2, CPU×1.951; 8192→16384: size×2, CPU×2.118; 16384→32768: size×2, CPU×2.000; 32768→262144: size×8, CPU×7.653; 262144→1048576: size×4, CPU×4.318; 1048576→4194304: size×4, CPU×4.457.
- benign before: 4096→8192: size×2, CPU×1.899; 8192→16384: size×2, CPU×1.958; 16384→32768: size×2, CPU×2.046.
- benign after: 4096→8192: size×2, CPU×2.229; 8192→16384: size×2, CPU×1.801; 16384→32768: size×2, CPU×1.470; 32768→262144: size×8, CPU×5.238; 262144→1048576: size×4, CPU×3.818; 1048576→4194304: size×4, CPU×4.143.
- title before: 4096→8192: size×2, CPU×4.190; 8192→16384: size×2, CPU×3.817; 16384→32768: size×2, CPU×4.475.
- title after: 4096→8192: size×2, CPU×1.890; 8192→16384: size×2, CPU×2.054; 16384→32768: size×2, CPU×1.899; 32768→262144: size×8, CPU×8.123.

Interpretation: baseline script/style/alternating/malformed/title doublings cluster around ~4×. Known raw script/style paths now scan approximately linearly; malformed tags reject early, plus one bounded full UTF-8 decode, rather than reproducing quadratic completion. Larger after-only sizes reach the full 4MiB limit for three required malicious families and controls. Repeated ordinary tags at 4MiB cost ~3.4s CPU, with roughly proportional scaling, and benign HTML at 4MiB ~0.7s; these higher constants are documented, not hidden behind only fast malicious examples. At 32KiB benign pages remain around milliseconds, but are slower than the original C-heavy substitutions. Title extra family is measured through 256KiB; maximum-size single-title retention tested separately. No comparable quadratic pattern found in tested malformed families. This supports the forward-scan argument; it does not establish a hard total CPU deadline or prove every possible Python/runtime worst case.

## 13–15. Adversarial tests, preserved controls and final regressions
43 new H01–H24 cases plus targeted maximum Unicode/input and bounded-entity tests exercise actual production fetch_url/tool paths with fake body bytes. Cover scripts/styles/comments/quoted attributes, malformed/incomplete/oversized tags, raw-text nesting, title behavior, entities, whitespace, Unicode, output limits, source/tool provenance, search contract, and non-citable failed fetches. Structural tests forbid delegation to DOM/global re.sub and assert bounded entity-decoder input. Scaling evidence supplements assertions; no fragile wall-time pass threshold.

The V13/V14 safe_http.py is byte-identical to committed baseline, preserving _public/_target/_PinnedConnection, rawHTTP/decode caps, wire/redirect budgets, cleanup, TLS/SNI/Host and proxy fail-closed checks. Provider, executor, spending ledger/reservations/validator, canonical policy, model/SDK retry configuration and report contracts unchanged. All existing tests untouched. Canonical state draft, no active policy/ledger. No network permission or credential changes.

Tests run in exact full disposable Git export of d52378c plus exact current retrieval.py/new tests, /tmp/v14-evidence/tree. Before/after source hashes: /tmp/v15-evidence/snapshot-hashes.json. The previously approved unchanged external run.py/child.py/isolation/sitecustomize.py were byte-compared to original harness entries in the independently approved V14 bundle. No invented replacement. Credential-free child environment, socket DNS/connect/sendto audit guard and source/canonical write guard retained. Native V6 evidence only inside disposable checkout, other evidence under /tmp/v15-evidence/regression. Fresh 62 V6 case files and native exit_status=0 verified against external census. Source/test files unchanged after tests. Time/resource limits 90s wall/45s CPU/1GiB AS/16MiB file. Groups overlap, do not sum.

### html

```bash
python /tmp/v14-evidence/run.py v151_html tests/test_html_extraction.py -q -ra -p no:cacheprovider
```
Initial collected 43; selected 43; passed 43; failed 0; skipped 0; xfailed 0; xpassed 0; deselected 0; pytest/process exit 0; no timeout; teardown reports 43, errors 0; session finish successful; collection/internal errors 0. Source identity exact V15 bytes over stated baseline. Logs/census /tmp/v14-evidence/v151_html.log, v151_html.json, v151_html_summary.json.

### fetch

```bash
python /tmp/v14-evidence/run.py v151_fetch tests/test_tools.py::test_fetch_page_extracts_text -q -ra -p no:cacheprovider
```
Initial collected 1; selected 1; passed 1; failed 0; skipped 0; xfailed 0; xpassed 0; deselected 0; pytest/process exit 0; no timeout; teardown reports 1, errors 0; session finish successful; collection/internal errors 0. Source identity exact V15 bytes over stated baseline. Logs/census /tmp/v14-evidence/v151_fetch.log, v151_fetch.json, v151_fetch_summary.json.

### tools

```bash
python /tmp/v14-evidence/run.py v151_tools tests/test_tools.py tests/test_orchestration.py tests/test_recovery.py tests/test_phase4.py -q -ra -p no:cacheprovider
```
Initial collected 23; selected 23; passed 23; failed 0; skipped 0; xfailed 0; xpassed 0; deselected 0; pytest/process exit 0; no timeout; teardown reports 23, errors 0; session finish successful; collection/internal errors 0. Source identity exact V15 bytes over stated baseline. Logs/census /tmp/v14-evidence/v151_tools.log, v151_tools.json, v151_tools_summary.json.

### ssrf

```bash
python /tmp/v14-evidence/run.py v151_ssrf tests/test_ssrf.py -q -ra -p no:cacheprovider
```
Initial collected 54; selected 54; passed 54; failed 0; skipped 0; xfailed 0; xpassed 0; deselected 0; pytest/process exit 0; no timeout; teardown reports 54, errors 0; session finish successful; collection/internal errors 0. Source identity exact V15 bytes over stated baseline. Logs/census /tmp/v14-evidence/v151_ssrf.log, v151_ssrf.json, v151_ssrf_summary.json.

### bounded

```bash
python /tmp/v14-evidence/run.py v151_bounded tests/test_bounded_retrieval.py -q -ra -p no:cacheprovider
```
Initial collected 43; selected 43; passed 43; failed 0; skipped 0; xfailed 0; xpassed 0; deselected 0; pytest/process exit 0; no timeout; teardown reports 43, errors 0; session finish successful; collection/internal errors 0. Source identity exact V15 bytes over stated baseline. Logs/census /tmp/v14-evidence/v151_bounded.log, v151_bounded.json, v151_bounded_summary.json.

### full

```bash
python /tmp/v14-evidence/run.py v151_full tests audit_v3/test_independent_guard.py audit_v4/test_v4_adversarial.py audit_v4/test_v4_review.py policy_v5/test_policy_validation.py policy_v6/test_v6_validator.py policy_v7/test_v7_policy.py policy_v7/followup/test_blocked_policy.py --audit-output /tmp/v15-evidence/regression/v3 --policy-audit-output /tmp/v15-evidence/regression -q -ra -p no:cacheprovider -k 'not test_live_end_to_end'
```
Initial collected 480; selected 479; passed 477; failed 0; skipped 2; xfailed 0; xpassed 0; deselected 1; pytest/process exit 0; no timeout; teardown reports 479, errors 0; session finish successful; collection/internal errors 0. Source identity exact V15 bytes over stated baseline. Logs/census /tmp/v14-evidence/v151_full.log, v151_full.json, v151_full_summary.json.

Full regression 477 passed /2 historical V5 skips/1 paid live test deselected. All old 434 passing cases remain, plus 43 new passing cases. Two gzip-parametrized node IDs contain collection-time gzip timestamps; comparison normalizes that unchanged six-case function by function/outcome with matching multiplicity, while every other prior node/outcome is compared exactly. Existing test source hashes are unchanged. Successful process exit verified after native session-finish hooks; no incomplete census/teardown suppression.

## 16. Remaining limitations
No hard end-to-end deadline across synchronous DNS/TLS initialization/parsing; V15 improves work complexity but is not preemptive CPU scheduling. Token/name/title limits impose documented strictness on some valid huge-attribute pages. Scanner is not full HTML5 tree building, a content sanitizer, CSS/JavaScript evaluator or universal visibility oracle. No live network/real TLS behavior verified. Required proxies still fail closed; V14 chunk-budget errors may still surface as IncompleteRead. Search's independent regex result parser is unchanged and not certified against arbitrary worst-case markup by this extraction fix. Calculator exhaustion, unsupported claims, zero-citation approval, provider entitlements/billing and spending/deployment prerequisites remain separate work. No claim of formal runtime-wide O(N), process RSS cap or deployment readiness.

## 17–18. Minimal patch and independent Muse handoff
Complete unified patch including new tests/report: /tmp/v15-evidence/V15_COMPLETE.patch. Exact modified file hashes and protected-state evidence: /tmp/v15-evidence/final-integrity.json. Original baseline source, parser-inspection notes, resource contract, benchmark scripts/records and all regression evidence retained for independent audit. Muse has not reviewed V15 yet.

Audit plan: independently reconstruct the baseline, replace network read with the same finite fixture bytes and reproduce original 4–32KiB scaling; use calibrated batches and separate tracemalloc peaks; run after families to 4MiB, retaining the documented bounded 90s trace retry for repeated ordinary tags. Inspect cursor monotonicity, bounded tag/name/entity operations, fixed regex grammar, suppression and output-list caps; inspect malformed input and memory widening using maximum-size Unicode. Verify titles/entities/comments/attributes and unchanged failed-fetch non-citation. Independently rerun V13, V14 and full tests with the exact current source in disposable checkout and original verified harness; inspect teardown/native evidence. Check residual timing/compatibility assumptions. No network installation or live request needed.

Next action: independent Muse audit of the V15 scanner, scaling corpus and malformed-HTML resource contract.

### Current code SHA-256

- `src/tools/retrieval.py`: `7c0b6ba90972489623f66f7e666453ce4a5b3797e61a40177ab4adf24867b665`
- `tests/test_html_extraction.py`: `699f6e639152bb006edcb97c333d92d31e4562b1537e4a065117cc9d61d7bd79`
