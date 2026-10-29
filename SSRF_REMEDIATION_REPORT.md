# SSRF remediation report — V13.1

## 1. Executive verdict
Implemented; ready for independent audit on deterministic offline evidence. All identified attacker-influenced production research HTTP sinks use connection-level destination enforcement. No demonstrated private-destination bypass remains. Proxy-required environments, including this managed runtime, deliberately fail closed: no trusted-proxy destination-enforcement contract is available. This is a security boundary, not certification of live retrieval or deployment readiness.

## 2. Repository and baseline
Configured repository gchalono/autonomous-research, branch policy-validator-repair, HEAD 2cd30eba4bfe95bc224d317a8216c212840ac757. Expected branch/HEAD verified. Initially clean tracked tree and index, 569 unrelated untracked files preserved. Initial status and tracked hashes saved under /tmp/v13-evidence/status-before.txt and protected.json. No commit, push, merge, deployment, paid call or external request occurred.

## 3. Production sink inventory
| Path | Input source | Actual transport | Redirect behavior | Proxy behavior | Protection / scope |
|---|---|---|---|---|---|---|
| fetch_page tool → retrieval.fetch_url | user/model/tool URL | formerly urllib.urlopen, now safe_http → pinned HTTPConnection | formerly automatic, now each hop validated | previously inherited, now refusal | In scope, protected |
| engine → verifier → default fetch_fn=fetch_url | report/search/model source URLs | same protected boundary | same | same | In scope, protected; Python-injected alternate fetch_fn is trusted application wiring, not attacker URL configuration |
| search._search_duckduckgo | fixed host, query encoded; server controls redirect URL | formerly urllib.urlopen, now safe_http | all hops validated | refusal | In scope because redirects select destinations, protected |
| search._search_tavily → _open_tavily | query in body to fixed api.tavily.com/search | guarded urllib opener | _NoRedirect refuses | existing inherited behavior | Trusted provider API, unchanged/outside research-page scope |
| llm.OpenAIProvider → guard → SDK | restricted configured endpoint/models | guarded SDK HTTP | disabled | existing configuration | Trusted provider API, unchanged |
| Other production components | searched requests/httpx/urllib/aiohttp/urlopen/custom transports across src | no other attacker-URL HTTP sink found | n/a | n/a | No uncovered attacker-influenced sink identified |

## 4. Pre-fix reproduction
Before production edits, fake urllib transport recorded http://127.0.0.1/secret through real fetch_url. The zero-dispatch assertion failed: collected 1, passed 0, failed 1, skipped/xfail/xpass 0, exit 1. No real DNS or connection occurred.
Command: `.venv/bin/python -m pytest /tmp/v13-evidence/test_prefix.py -q -p no:cacheprovider`.
Evidence: /tmp/v13-evidence/prefix.log and test_prefix.py. This proves the old sink; permanent tests observe the replacement socket boundary.

## 5. Destination policy
Absolute HTTP(S) only, consistent urlsplit/IDNA normalization, strict host labels/authority/ports. Reject credentials, controls/whitespace, backslash, scoped IPv6, percent authority, noncanonical numeric IPv4, malformed host/ports/IPv6. Provider API hostnames remain excluded as source pages. Every DNS answer must be valid and globally routable; any invalid/private/mixed/empty answer rejects before creating a socket. Direct IPs skip DNS.
Reject non-global, multicast, reserved, loopback, link-local, unspecified, IPv4-mapped IPv6. Explicitly reject IPv4 192.0.0.0/24 and 192.88.99.0/24; IPv6 must be in 2000::/3 and outside 2001::/23, 2002::/16, 3fff::/20. This conservative policy may exclude some legitimate special-purpose services and avoids relying exclusively on is_private or version-dependent transition-address classification.

## 6. Connection enforcement
Installed Python 3.12.14 stdlib HTTPConnection normally uses socket.create_connection, which can resolve again. New private subclass overrides connect and directly creates an AF_INET/AF_INET6 socket, then socket.connect receives only an ipaddress-produced numeric literal. No ordinary hostname connect, connection pooling, fallback resolver, tunnel, retry or alternate-address attempt exists. Standard library handles HTTP framing; no new dependency or ad hoc TLS protocol.
HTTPS uses ssl.create_default_context().wrap_socket with server_hostname equal to the original canonical host; CERT_REQUIRED/check_hostname preserved. HTTP Host is the original authority including nondefault port. Positive tests execute HTTPConnection serialization and HTTPResponse parsing on fake sockets, recording attempts and established connections separately. TLS tests inspect real default-context verification configuration, original-host argument and certificate-failure propagation; no real TLS handshake is claimed.

## 7. DNS rebinding
Fake resolver public-first/private-second: only one resolution per hop occurs; actual socket destination remains public. Redirect resolution is fresh and rejects a newly private answer before that hop creates a socket. Direct literals produce no DNS call. A malicious public service, OS routing/transparent interception, compromised resolver infrastructure or CA store lies outside this direct-connection SSRF guarantee.

## 8. Redirects and required proxies
No automatic redirects. Maximum six requests (initial plus five redirects), normalized visited-hop loop detection. All destination policy is reapplied per hop; relative Location resolves then validates. Controls/backslashes checked before urljoin can normalize them away. Private/unsupported redirect targets fail; valid public HTTPS redirects succeed. A valid first hop may connect before a malicious redirect is discovered; the disallowed hop has zero attempts.
getproxies() plus explicit case-insensitive HTTP_PROXY/HTTPS_PROXY/ALL_PROXY environment checks cause refusal before DNS or sockets. NO_PROXY never bypasses this rule. Explicit check covers CGI environments that make urllib ignore HTTP_PROXY. No global environment or managed-proxy change/bypass performed. Operation through a required proxy would need independently proven destination validation/pinning, per-hop enforcement and original-host TLS at the proxy's real connection boundary. No such contract is present; retrieval remains unavailable in proxy-required runtimes.

## 9. Exact diff inventory
Production: modified src/tools/retrieval.py and src/tools/search.py at research transport boundary; added src/tools/safe_http.py. Tests: added tests/test_ssrf.py; updated two mocks in tests/test_tools.py to the new boundary, preserving every existing assertion. Tavily/API integration unchanged. No unrelated refactor or new dependency.

## 10–11. Adversarial and regression results
Commands below ran through credential-free socket audit isolation, 90s wall /45s CPU /1GiB AS /16MiB file limits. Exact current source bytes matched snapshot. Writes to real repo and canonical test policy/ledger paths denied. Fake socket methods record numeric destinations; no live DNS or external/internal connections. Groups overlap; do not sum them.

### ssrf

```bash
python /tmp/v13-evidence/run.py ssrf tree tests/test_ssrf.py -q -ra -p no:cacheprovider
```
Collected 54; selected 54; outcomes {'passed': 54}; failed 0; xfailed 0; xpassed 0; deselected 0; exit 0.

### fetch

```bash
python /tmp/v13-evidence/run.py fetch tree tests/test_tools.py::test_fetch_page_extracts_text -q -ra -p no:cacheprovider
```
Collected 1; selected 1; outcomes {'passed': 1}; failed 0; xfailed 0; xpassed 0; deselected 0; exit 0.

### tools_orchestration

```bash
python /tmp/v13-evidence/run.py tools_orchestration tree tests/test_tools.py tests/test_orchestration.py tests/test_recovery.py tests/test_phase4.py -q -ra -p no:cacheprovider
```
Collected 23; selected 23; outcomes {'passed': 23}; failed 0; xfailed 0; xpassed 0; deselected 0; exit 0.

### offline_regression

```bash
python /tmp/v13-evidence/run.py offline_regression tree tests audit_v3/test_independent_guard.py audit_v4/test_v4_adversarial.py audit_v4/test_v4_review.py policy_v5/test_policy_validation.py policy_v6/test_v6_validator.py policy_v7/test_v7_policy.py policy_v7/followup/test_blocked_policy.py --audit-output /tmp/v13-evidence/regression/v3 --policy-audit-output /tmp/v13-evidence/regression -q -ra -p no:cacheprovider -k 'not test_live_end_to_end'
```
Collected 394; selected 393; outcomes {'passed': 391, 'skipped': 2}; failed 0; xfailed 0; xpassed 0; deselected 1; exit 0.

SSRF cases cover every S01–S20 requirement through production fetch_url/tool paths, actual socket selection, real HTTP framing and fake DNS/TLS. Additional tests cover transition/special addresses, scoped DNS answers, CGI proxy omission, redirect-time rebinding and certificate failure. Initial rejected requests have zero attempts; redirects have zero disallowed-hop attempts. Positive tests observe public IPv4/IPv6, Host and original-host TLS parameters. Two historical V5 pricing tests remain skipped; one paid live test deselected. No unexpected failures or existing assertion weakening. During development four new fixture expectations failed (text extraction inserts a space; DuckDuckGo snippet fixture required an anchor); corrected fixture expectations without changing production extraction/parser semantics. Final counts above supersede intermediate runs.

## 12. Preserved invariants and integrity
All tracked bytes outside the three authorized fetch/test files match the pre-task inventory. Provider.py, executor.py, spending implementation, policy validator, model config, report contracts, SDK retry settings and canonical policy unchanged. Policy state draft; no canonical active policy or spending ledger. Index remains empty. Secret-pattern scan clean after explicitly identifying only the synthetic u:p@example.com credential-rejection fixture; no actual credential added. final-integrity.json and SSRF_COMPLETE.patch in /tmp/v13-evidence contain full hashes/diff, including new files.

## 13. Remaining limitations
Proxy-dependent retrieval unavailable pending trusted enforcement integration; no live site/API acceptance or billing verification. Response bodies remain unbounded: extracted 12000-character cap is not a streaming download cap. DNS/per-hop read timeout is not a complete resource budget. Calculator exhaustion, unsupported factual claims, zero-citation approval and research correctness remain separate tasks. Unsupported trusted application injection/custom networking is not an attacker-facing URL path. No financial or deployment readiness claim.

## 14. Independent-review handoff
Inspect src/tools/safe_http.py, src/tools/retrieval.py, src/tools/search.py, tests/test_ssrf.py and tests/test_tools.py. Independently verify numeric socket destinations, all-answer validation, TLS original authority, redirect/proxy handling and required-proxy availability limitation. Reproduce recorded commands using the existing runner/isolation and inspect per-case JSON/logs under /tmp/v13-evidence. Required next action: independent audit of this uncommitted bounded remediation before any commit or activation.

### Full current code hashes

- `src/tools/retrieval.py`: `ee952fdaa793f9f85d30498511bf8e8bb3b4c2b509638682bdfcbc73da4dc38c`
- `src/tools/search.py`: `10153d1564b6b24ec00b7aaaf245f22323711801c7c4d0e268ad01f85b9be041`
- `tests/test_tools.py`: `8af6bcb72ea8a4bc46c0081029dd37651071e858b2050d1f57eaf338afa9f488`
- `src/tools/safe_http.py`: `c10790bd92c137ee61c992de91e1a75bad210cf84cad6db167fef58104de065b`
- `tests/test_ssrf.py`: `7f7113f0f9d9cea4d1adf54bfa20c703d9b42443357b800bb876f97c27a35cef`
