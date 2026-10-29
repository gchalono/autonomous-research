# V14.1 bounded retrieval report

## 1. Executive verdict
Implemented bounded HTTP-byte consumption and incremental decompression, with offline evidence; ready for independent audit, not committed/deployed. Both research-page fetch paths use the same V13-protected transport. No overflow is returned as successful truncated HTML. Time enforcement is PARTIAL: remaining-time socket deadlines and monotonic checks constrain cooperative transport/body work, but synchronous DNS, TLS-context initialization and downstream decoding/HTML parsing cannot be safely preempted here. No hard all-stage wall-clock guarantee is claimed. No external network or paid calls occurred.

## 2. Baseline and working tree
Repository gchalono/autonomous-research, configured origin https://github.com/gchalono/autonomous-research.git, branch policy-validator-repair, committed baseline 927dc73481e10e3152f9bf7247d4c37d09042879. Branch/HEAD match; index and tracked working tree initially clean. Existing 569 unrelated untracked files preserved. Complete initial status and tracked hashes: /tmp/v14-evidence/status-before.txt, baseline-hashes.json. No Git remote operation, staging, commit, rebase, configuration/environment edit or network install.

## 3. Response-consumption inventory
| Path | Transport / reading | Decompression | Timeout and prior limits |
|---|---|---|---|
| tool/model/user URL → fetch_page → retrieval.fetch_url | safe_http pinned HTTPConnection; previously resp.read() without size | stdlib HTTPResponse performs transfer framing only, no Content-Encoding decompression | V13 socket timeout 30s; five redirects; extraction capped at 12000 characters only |
| engine → source verifier → default fetch_fn=fetch_url | same source-page boundary | same | same |
| search._search_duckduckgo (fixed search host plus redirects) | same read_public_url boundary; then UTF-8/regex result extraction | same | same |
| trusted Tavily search API | guarded fixed-endpoint urllib response read | existing provider behavior | Outside research-page scope, unchanged |
| trusted OpenAI API | guarded SDK | existing provider behavior | Outside scope, unchanged |

Flow: untrusted URL → unchanged V13 parsing/address validation → unchanged pinned connection/TLS → bounded raw socket-file reader → stdlib HTTP framing → bounded encoded-body reads → bounded identity/gzip/deflate decoding → UTF-8 replacement decoding → existing HTML/search extraction → existing tool output. No second transport or bypass introduced.

## 4. Pre-fix reproduction
Before production editing, a finite fake response advertised Content-Length: 1 and yielded 2097152 body bytes through real read_public_url. Observed raw_bytes=2097152, response_closed=true, connection_closed=true. The zero-overflow assertion requiring <=1048577 failed. Collected 1, passed 0, failed 1, skipped/xfail/xpass 0, exit 1; no timeout. Thus cleanup existed but body bounds did not.

```bash
.venv/bin/python -m pytest /tmp/v14-evidence/test_prefix.py -q -s -p no:cacheprovider
```

Evidence: prefix.log and test_prefix.py. This is a response-adapter demonstration, not a claim that stdlib HTTPResponse ignores Content-Length. Post-fix tests additionally use real stdlib framing with counted socket-file reads: an underreported length delivers only the declared message body and closes the connection; prefetched bytes are separately counted and bounded.

## 5. Exact numeric byte policy
Defaults selected before implementation in /tmp/v14-evidence/LIMIT_POLICY.md are conservative engineering assumptions, not benchmark-derived; validate against future research workloads.

| Resource | Exact limit / interpretation |
|---|---|
| Encoded body data delivered by HTTPResponse per final response | 1048576 bytes accepted; at most 1048577 delivered to detect overflow. Not a claim that only this amount was downloaded due to framing and prefetch |
| Decoded output retained | 4194304 bytes. Decompression uses a separate remaining-output allowance; at most 4194305 decoded candidate bytes across retained output plus current candidate before rejection |
| HTTP plaintext from unbuffered socket-file boundary, whole redirect chain | 2097152 accepted, at most 2097153 consumed to detect overflow. Includes status/headers, transfer metadata, buffered prefetch and encoded body. This is the actual aggregate HTTP-consumption security budget |
| Body read request | <=16384 bytes via HTTPResponse.read1, additionally limited by remaining encoded allowance +1 |
| HTTP buffered reader | 8192 bytes; its underlying readinto request is capped by remaining chain budget +1 |
| Redirects | Existing five redirects, six total requests. Redirect bodies are not deliberately consumed; any prefetch counts against the shared chain budget |

The hard consumed-byte limit includes one-byte overflow probes. TCP/IP headers, encrypted TLS records/handshake traffic and kernel receive buffers are outside the HTTP plaintext-byte metric. Python's SocketIO.readinto/SSL application-data interface returns at most its supplied buffer size; source inspection in transport-contract.txt. No claim of exact encrypted network-wire byte accounting. A malicious peer may send more bytes onto the network than the client chooses to consume.

No full encoded body is accumulated: encoded chunks <=16KiB, parser buffer <=8KiB; zlib tails are bounded by input chunks. Output bytearray length <=4MiB, current decoded candidate <=4MiB+1, and final immutable copy <=4MiB. These bound logical intermediate buffers; bytearray overallocation, zlib state, parsed headers and Unicode/regex intermediates add bounded implementation overhead. No fixed RSS/allocator ceiling is claimed. Headers/transfer metadata share the 2MiB chain budget, and stdlib also limits header lines/count. HTML extraction receives finite decoded input; no large retained text bypass via character-only counting.

## 6. Time guarantees
Socket inactivity/connect timeout becomes min(10 seconds, remaining operation time). A single 60-second monotonic budget starts before resolution and spans redirect targets, connection/header acquisition, raw reads, body/decompression loops and completion checks. Slow continuing raw input is checked before every underlying read; buffered body work is checked per read1/decompression iteration. Tests with a clock advanced per byte terminate continuous delivery at the budget. No deadline reset per hop.

Limitations: synchronous socket.getaddrinfo has no safe per-call cancellation in this architecture; time is checked immediately after it returns, not while blocked. TLS trust-context initialization, CPU scheduling, and downstream UTF-8/HTML/search parsing are not preempted. A socket timeout is not a hard total deadline, nor does the Tool timeout metadata enforce one. Overall status TIME_LIMIT_ENFORCED: PARTIAL. A hard all-stage guarantee requires separately scoped cancellable resolver/worker isolation; no architecture expansion undertaken.

## 7. Streaming and framing
The smallest transport change adds a socket-file adapter using makefile(mode, buffering=0), a RawIOBase budget counter below an 8KiB BufferedReader, and bounded HTTPResponse.read1 requests. It preserves stdlib HTTP parsing instead of implementing framing manually. Raw count includes header/chunk overhead and prefetch, avoiding hidden unmetered buffered reads. Standard SocketIO.readinto and HTTPResponse.read1 contracts were inspected, retained in transport-contract.txt. Oversized/malformed adapter output is rejected before appending to output; the deliberately broken-adapter test is defense in depth and not evidence of a different real transport contract.

Content-Length is advisory: invalid/negative/ambiguous/huge values reject; correct or missing values still use bounded reads. Overreported/truncated bodies reject at EOF. Underreporting cannot trigger unbounded reading: standard framing stops at its declared message length and the connection is closed, while limited prefetch still counts. Contradictory Content-Length + Transfer-Encoding and unsupported transfer encoding reject. Chunk framing cannot exhaust unbounded input because all bytes below its parser share the wire budget.

## 8. Decompression and character decoding
http.client exposes encoded body bytes; no auto Content-Encoding decompression occurs before the counter. Request advertises Accept-Encoding: identity. Unsolicited gzip and standard zlib-wrapped HTTP deflate are supported incrementally via zlib.decompressobj with explicit max_length=remaining decoded allowance+1. No unbounded flush or decompress call exists. Decoder EOF, zlib integrity errors, unconsumed input, trailing/concatenated gzip members and unsupported/stacked/Brotli encodings fail closed. No unsupported encoding advertised. Raw deflate without the standard zlib wrapper is intentionally unsupported rather than guessed.

UTF-8 errors='replace' remains unchanged downstream; binary/malformed input has predictable finite text output. Byte bounds apply before Unicode conversion. No content-type trust is needed for bounds. The existing 12000-character extraction cap remains a separate output policy, not a download limit.

## 9–10. Failure semantics, cleanup and cancellation
Oversize/raw-budget/decompressed-budget failures raise FetchBlocked; fetch_page returns ok=false and says the URL must not be cited as retrieved. No silent truncated HTML success. Responses and connections close in existing nested finally blocks on overflow, timeout, connection interruption, malformed framing/compression and asyncio cancellation. All created mock HTTPResponse objects are verified closed; no GC-only cleanup. Downstream parser failure occurs after the transport is already closed. No worker cancel architecture or universal asynchronous cancellation guarantee claimed.

## 11. V13 preservation
_public, _target and the entire _PinnedConnection class remain byte-identical to the approved V13 baseline. HTTP(S) parsing, all-answer public-DNS checks, numeric IP pinning, rebinding resistance, redirect revalidation/limits, required-proxy refusal, TLS default-context certificate verification, original-host SNI/Host, and no connection-pool fallback preserved. Only the instance timeout, response file wrapper and Accept-Encoding/header/body handling change at dispatch. All original 54 SSRF tests pass unchanged; new resource tests also verify private/proxy refusal, public HTTPS and single-resolution pinning.

## 12. Adversarial matrix and measured evidence
43 new tests in tests/test_bounded_retrieval.py cover B01–B26, plus exact decoded boundaries for both supported encodings, contradictory framing, shared redirect byte budget, framing overhead and post-DNS deadline checks. Fake socket raw input carries real HTTP/chunk framing and real gzip/deflate bytes; real HTTPResponse, zlib and production bounded reader run. No fake iterator silently decompresses before measurement. Rejected cases record closure and numeric connection attempts; existing V13 suite covers zero attempts to forbidden destinations.

Per-case records: /tmp/v14-evidence/measurements/bounded/*.json (focused) and measurements/offline_regression/*.json (full replay). Fields include advertised length, HTTP plaintext bytes actually read, encoded body delivered, decoded candidate total, maximum logical output retained, raw read count, largest body request, closure, connection addresses and result/exception. The oversized-response-method test deliberately replaces read1; its artificial returned bytes are not counted by the normal spy, so its body_delivered=0 is not a raw-byte assertion. Its meaningful evidence is zero oversized output retained and rejection/cleanup. Other rows use actual HTTP framing. Tool/parsing observations are recorded where applicable.

| Case | Advertised length | Raw HTTP bytes | Encoded body delivered | Decoded probe total | Max retained output | Raw reads | Closed | Result |
|---|---|---:|---:|---:|---:|---:|---|---|
| test_B01_B03_exact_boundary[-1] | None | 1048594 | 1048575 | 1048575 | 1048575 | 66 | True | accepted |
| test_B01_B03_exact_boundary[0] | None | 1048595 | 1048576 | 1048576 | 1048576 | 66 | True | accepted |
| test_B01_B03_exact_boundary[1] | None | 1048596 | 1048577 | 1040365 | 1040365 | 65 | True | FetchBlocked |
| test_B04_invalid_or_huge_declared_length[-1] | -1 | 40 | 0 | 0 | 0 | 1 | True | FetchBlocked |
| test_B04_invalid_or_huge_declared_length[1, 2] | 1, 2 | 42 | 0 | 0 | 0 | 1 | True | FetchBlocked |
| test_B04_invalid_or_huge_declared_length[999999999999999999999999] | 999999999999999999999999 | 62 | 0 | 0 | 0 | 1 | True | FetchBlocked |
| test_B04_invalid_or_huge_declared_length[invalid] | invalid | 45 | 0 | 0 | 0 | 1 | True | FetchBlocked |
| test_B05_underreported_real_framing_is_not_an_unbounded_read | 1 | 8192 | 1 | 1 | 1 | 1 | True | accepted |
| test_B06_missing_or_overreported_length[headers0] | None | 1048596 | 1048577 | 1040365 | 1040365 | 65 | True | FetchBlocked |
| test_B06_missing_or_overreported_length[headers1] | 100 | 41 | 1 | 1 | 1 | 2 | True | FetchBlocked |
| test_B07_chunked_body | None | 1048632 | 1048577 | 1040329 | 1040329 | 65 | True | FetchBlocked |
| test_B08_oversized_response_api_chunk_rejected | 1 | 39 | 0 | 0 | 0 | 1 | True | FetchBlocked |
| test_B09_continuous_delivery_deadline | None | 240 | 221 | 221 | 221 | 240 | True | FetchBlocked |
| test_B10_B11_B22_exception_cleanup[error0] | 7 | 38 | 0 | 0 | 0 | 39 | True | TimeoutError |
| test_B10_B11_B22_exception_cleanup[error1] | 7 | 38 | 0 | 0 | 0 | 39 | True | ConnectionResetError |
| test_B10_B11_B22_exception_cleanup[error2] | 7 | 38 | 0 | 0 | 0 | 39 | True | CancelledError |
| test_B12_B13_expansion_bomb[deflate-compress] | 4086 | 4154 | 4086 | 4194305 | 0 | 1 | True | FetchBlocked |
| test_B12_B13_expansion_bomb[gzip-compress] | 4098 | 4163 | 4098 | 4194305 | 0 | 1 | True | FetchBlocked |
| test_B14_B15_invalid_unsupported_or_trailing_compression[br-bomb] | None | 45 | 0 | 0 | 0 | 1 | True | FetchBlocked |
| test_B14_B15_invalid_unsupported_or_trailing_compression[deflate-bad] | None | 49 | 3 | 0 | 0 | 1 | True | FetchBlocked |
| test_B14_B15_invalid_unsupported_or_trailing_compression[gzip, deflate-bomb] | None | 56 | 0 | 0 | 0 | 1 | True | FetchBlocked |
| test_B14_B15_invalid_unsupported_or_trailing_compression[gzip-\x1f\x8b\x08\x00\x8d?\xe3j\x02\xff\xcb\xcf\x06\x00G\xdd\xdcy\x02\x00\x00\x00\x1f\x8b\x08\x00\x8d?\xe3j\x02\xffK\xad()J\x04\x00e\r?M\x05\x00\x00\x00] | None | 90 | 47 | 2 | 2 | 1 | True | FetchBlocked |
| test_B14_B15_invalid_unsupported_or_trailing_compression[gzip-\x1f\x8b\x08\x00\x8d?\xe3j\x02\xff\xcb\xcf\x06\x00G\xdd\xdcy\x02\x00] | None | 63 | 20 | 2 | 2 | 2 | True | FetchBlocked |
| test_B14_B15_invalid_unsupported_or_trailing_compression[gzip-\x1f\x8b\x08\x00\xf2?\xe3j\x02\xff\xcb\xcf\x06\x00G\xdd\xdcy\x02\x00\x00\x00\x1f\x8b\x08\x00\xf2?\xe3j\x02\xffK\xad()J\x04\x00e\r?M\x05\x00\x00\x00] | None | 90 | 47 | 2 | 2 | 1 | True | FetchBlocked |
| test_B14_B15_invalid_unsupported_or_trailing_compression[gzip-\x1f\x8b\x08\x00\xf2?\xe3j\x02\xff\xcb\xcf\x06\x00G\xdd\xdcy\x02\x00] | None | 63 | 20 | 2 | 2 | 2 | True | FetchBlocked |
| test_B14_B15_invalid_unsupported_or_trailing_compression[gzip-bad] | None | 46 | 3 | 0 | 0 | 1 | True | FetchBlocked |
| test_B16_redirect_body_not_consumed | 2 | 8232 | 2 | 2 | 2 | 2 | True | accepted |
| test_B17_B18_binary_and_malformed_utf8[<title>T<_title><p>\xfftext<_p>] | 28 | 67 | 28 | 28 | 28 | 1 | True | accepted_body |
| test_B17_B18_binary_and_malformed_utf8[body0] | 256 | 296 | 256 | 256 | 256 | 1 | True | accepted_body |
| test_B19_B20_html_and_search_contract | 103 | 237 | 158 | 103 | 103 | 2 | True | accepted_body |
| test_B21_oversize_tool_failure_not_truncation | None | 1048596 | 1048577 | 1040365 | 1040365 | 65 | True | fetch failed (FetchBlocked: response body exceeds byte limit); this URL must not be cited as retrieved |
| test_B23_B25_v13_refusal[private] | 0 | 0 | 0 | 0 | 0 | 0 | False | FetchBlocked |
| test_B23_B25_v13_refusal[proxy] | 0 | 0 | 0 | 0 | 0 | 0 | False | FetchBlocked |
| test_B24_B26_rebinding_and_https_authority | 2 | 40 | 2 | 2 | 2 | 1 | True | accepted |
| test_contradictory_framing_refused | 10 | 72 | 0 | 0 | 0 | 1 | True | FetchBlocked |
| test_deadline_checked_after_blocking_resolver_returns | 0 | 0 | 0 | 0 | 0 | 0 | False | FetchBlocked |
| test_decoded_exact_boundaries[-1-deflate-compress] | None | 4132 | 4086 | 4194303 | 4194303 | 2 | True | accepted |
| test_decoded_exact_boundaries[-1-gzip-compress] | None | 4141 | 4098 | 4194303 | 4194303 | 2 | True | accepted |
| test_decoded_exact_boundaries[0-deflate-compress] | None | 4132 | 4086 | 4194304 | 4194304 | 2 | True | accepted |
| test_decoded_exact_boundaries[0-gzip-compress] | None | 4141 | 4098 | 4194304 | 4194304 | 2 | True | accepted |
| test_decoded_exact_boundaries[1-deflate-compress] | None | 4132 | 4086 | 4194305 | 0 | 1 | True | FetchBlocked |
| test_decoded_exact_boundaries[1-gzip-compress] | None | 4141 | 4098 | 4194305 | 0 | 1 | True | FetchBlocked |
| test_downstream_parser_failure_has_closed_transport | 16 | 55 | 16 | 16 | 16 | 1 | True | accepted_body |
| test_redirect_chain_shares_wire_budget | 300 | 513 | 0 | 0 | 0 | 2 | True | FetchBlocked |
| test_wire_budget_includes_chunk_framing | None | 257 | 0 | 0 | 0 | 1 | True | FetchBlocked |

Connection/refusal cases without an HTTP response naturally have no response to close. Candidate output can reach decoded cap+1 to detect a bomb; it is not appended beyond the retained cap. Tests of cap-1/cap/cap+1 verify accepted/accepted/rejected for encoded data and both decompressed encodings. Shared wire counter includes ignored redirect-body prefetch and chunk framing. Tests of small Content-Length accurately report header/body prefetch rather than equating delivered body or returned text with downloaded bytes.

## 13. Exact offline verification
Tests ran in a full disposable export of the exact baseline overlaid with current V14 safe_http.py and the new test file. Every original snapshot source/config byte was verified unchanged after testing, and modified V14 bytes matched the actual working tree. Credentials unavailable; startup network socket/DNS audit guard retained for Python workers/subprocesses. No real DNS, public/private/metadata or paid provider connection. Bounds: 90s wall /45s CPU /1GiB AS /16MiB file. Assertions unchanged; no skips introduced. Groups overlap and must not be summed.

### bounded

```bash
python /tmp/v14-evidence/run.py bounded tests/test_bounded_retrieval.py -q -ra -p no:cacheprovider
```
Source cwd /tmp/v14-evidence/tree; initial collected 43; selected 43; passed 43; failed 0; skipped 0; xfailed 0; xpassed 0; deselected 0; exit 0; no timeout; teardown reports 43, teardown errors 0; collection/internal errors 0.

### ssrf

```bash
python /tmp/v14-evidence/run.py ssrf tests/test_ssrf.py -q -ra -p no:cacheprovider
```
Source cwd /tmp/v14-evidence/tree; initial collected 54; selected 54; passed 54; failed 0; skipped 0; xfailed 0; xpassed 0; deselected 0; exit 0; no timeout; teardown reports 54, teardown errors 0; collection/internal errors 0.

### fetch

```bash
python /tmp/v14-evidence/run.py fetch tests/test_tools.py::test_fetch_page_extracts_text -q -ra -p no:cacheprovider
```
Source cwd /tmp/v14-evidence/tree; initial collected 1; selected 1; passed 1; failed 0; skipped 0; xfailed 0; xpassed 0; deselected 0; exit 0; no timeout; teardown reports 1, teardown errors 0; collection/internal errors 0.

### tools_orchestration

```bash
python /tmp/v14-evidence/run.py tools_orchestration tests/test_tools.py tests/test_orchestration.py tests/test_recovery.py tests/test_phase4.py -q -ra -p no:cacheprovider
```
Source cwd /tmp/v14-evidence/tree; initial collected 23; selected 23; passed 23; failed 0; skipped 0; xfailed 0; xpassed 0; deselected 0; exit 0; no timeout; teardown reports 23, teardown errors 0; collection/internal errors 0.

### offline_regression

```bash
python /tmp/v14-evidence/run.py offline_regression tests audit_v3/test_independent_guard.py audit_v4/test_v4_adversarial.py audit_v4/test_v4_review.py policy_v5/test_policy_validation.py policy_v6/test_v6_validator.py policy_v7/test_v7_policy.py policy_v7/followup/test_blocked_policy.py --audit-output /tmp/v14-evidence/evidence/v3 --policy-audit-output /tmp/v14-evidence/evidence -q -ra -p no:cacheprovider -k 'not test_live_end_to_end'
```
Source cwd /tmp/v14-evidence/tree; initial collected 437; selected 436; passed 434; failed 0; skipped 2; xfailed 0; xpassed 0; deselected 1; exit 0; no timeout; teardown reports 436, teardown errors 0; collection/internal errors 0.


Full regression: 434 passed, two historical V5 pricing-evidence skips, one paid test_live_end_to_end deselected. All 391 previously passing nodes/outcomes remain, plus 43 new tests. Native V6 evidence writes permitted only in the disposable evidence locations using the previously corrected external harness; 62 fresh per-case files and validator_results.json generated and checked against external census. No primary-tree destructive hook. Logs, per-phase JSON, native V3/V4/V5/V6 evidence and hashes retained under /tmp/v14-evidence/. Final measurement instrumentation was replayed in both focused and full runs. No test assertion weakened; existing source tests unchanged.

## 14. Exact modified-file inventory and protected controls
- Modified production: src/tools/safe_http.py only.
- Added test: tests/test_bounded_retrieval.py only.
- Added report: V14_BOUNDED_RETRIEVAL_REPORT.md.

No other tracked file changed. provider.py, executor.py, spending reservations/ledger, policy validator, canonical policy, model selection/SDK retries, report schemas, dependencies, retrieval HTML parser, search parser and calculator unchanged. Policy state draft; no active canonical policy or ledger. Existing unrelated untracked files preserved; index remains empty; HEAD unchanged. Complete diff including new test/report exported as /tmp/v14-evidence/V14_COMPLETE.patch. No secrets or environment dumps included.

## 15. Remaining limitations
Total wall-clock deadline remains partial as detailed above. No live website, real TLS handshake or real resolver acceptance tested. Proxy-required retrieval remains intentionally unavailable under V13 until an independently enforceable proxy contract exists. Conservative size/time defaults need future authorized workload validation; multi-member gzip, raw-deflate, Brotli and stacked encodings reject rather than guess. Limits bound HTTP application bytes and logical buffers, not encrypted packet accounting or process RSS. Local OS/resolver/TLS stack integrity assumed. Existing extraction/search regex work is bounded by finite input size but has no hard CPU-time deadline; adversarial worst-case parsing remains an explicit residual timing risk, not fixed by byte caps.

Calculator exhaustion, unsupported factual claims, zero-citation approval, account/pricing applicability, inactive spending authorization and deployment readiness remain separate work. No next remediation started. No universal network or total-resource guarantee is claimed.

## 16. Independent-review handoff
Inspect exact current src/tools/safe_http.py and tests/test_bounded_retrieval.py, this report, original V13 baseline, /tmp/v14-evidence/V14_COMPLETE.patch, LIMIT_POLICY.md, transport-contract.txt, run.py, child.py, isolation/sitecustomize.py, and per-case measurements. Verify makefile buffering=0 and HTTPResponse.read1 contracts on supported Python versions; rawHTTP counter below buffering; max_length decompression and trailing-frame refusal; one-byte probes; shared redirects; cleanup; V13 byte identity; and explicit deadline gaps. Reproduce the listed commands in the current prepared disposable tree or recreate it from the recorded baseline plus exact source hashes. No network install or live access required. Independently review the assumptions and timing limitations before any commit authorization.

Next action: independent audit of this uncommitted V14 patch, including HTTP-byte accounting and partial deadline guarantees.

### Current tested source SHA-256

- `src/tools/safe_http.py`: `0691c1cc1e3625f5896d877e79fc7f7ebb2a9a0e694ce3e7ba91313cec922bc0`
- `tests/test_bounded_retrieval.py`: `66be358b6fd6b63566c7fae45441cd070d2e2f5533b1d9083eb741b36e9c71ee`
