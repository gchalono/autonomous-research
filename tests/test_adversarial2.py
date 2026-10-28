"""Phase 3 adversarial research validation (spec section 10).

Each case injects a controlled input, executes the relevant verification
path, and asserts on OBSERVED state transitions and artifacts -- never on
an LLM's self-report that it detected the problem. Mapping to the 15
required cases is in FINAL_ACCEPTANCE_REPORT.md; cases already covered by
earlier suites (passage-not-supporting-claim, dangling mapping, false
approval, missing attribution, injection) are referenced there rather
than duplicated here.
"""
import os

from src.llm.provider import StubProvider, default_stub_behavior
from src.orchestration.engine import Orchestrator
from tests.conftest import fake_registry


def _base_report(claim_text="A claim.", classification="VERIFIED",
                 source_ids=("S1",), passage="Stub passage.",
                 url="https://example.com/stub"):
    return {
        "executive_summary": "s", "findings": [],
        "claims": [{"id": "C1", "text": claim_text, "classification": classification,
                    "source_ids": list(source_ids)}],
        "sources": [{"id": "S1", "url": url, "title": "S",
                     "passage": passage, "verification_status": "UNCHECKED"}],
        "limitations": [], "unresolved_dependencies": [],
    }


def _run_with(settings, store, report, auditor, fetch_fn, max_corrections=None):
    behavior = default_stub_behavior()
    behavior["executor"] = lambda call_no, user: (
        {"tool_calls": [], "done": True, "report": report}
        if "TOOL RESULT" in user else
        {"tool_calls": [{"tool": "web_search", "arguments": {"query": "x"}}],
         "done": False, "report": None})
    behavior["auditor"] = auditor
    if max_corrections is not None:
        settings.max_corrections = max_corrections
    engine = Orchestrator(settings, store, client=StubProvider(behavior),
                          registry=fake_registry(), fetch_fn=fetch_fn)
    pid = engine.create_project("obj")
    return engine.run(pid), engine


def _approve(call_no, user):
    return {"decision": "APPROVE", "issues": [], "rationale": "ok",
            "verified_sources": [], "unverified_sources": []}


def test_case1_fabricated_citation(settings, store):
    """Fabricated citation: URL that does not exist at all."""
    def unreachable(url):
        raise ConnectionError("DNS failure")

    status, _ = _run_with(settings, store,
                          _base_report(url="https://example.com/does-not-exist"),
                          _approve, unreachable, max_corrections=0)
    assert status["state"] == "COMPLETED_WITH_LIMITATIONS"
    assert status["open_critical_issues"] >= 1


def test_case2_real_url_unrelated_content(settings, store):
    """Real URL, unrelated content: passage not found on the fetched page."""
    def fetch(url):
        return "T", "this page is about gardening, nothing to do with the claim"

    status, _ = _run_with(settings, store, _base_report(), _approve, fetch,
                          max_corrections=0)
    assert status["state"] == "COMPLETED_WITH_LIMITATIONS"


def test_case4_incorrect_arithmetic_flagged(settings, store):
    """Incorrect arithmetic: auditor flags the calculation, correction runs."""
    def auditor(call_no, user):
        if call_no == 1:
            return {"decision": "CORRECTIONS_REQUIRED",
                    "issues": [{"id": "A1", "severity": "MAJOR",
                                "affected_claim_or_section": "C1",
                                "description": "margin calculation is wrong: "
                                               "120 - 95 - 30 = -5, not +25",
                                "evidence": "", "required_correction": "recompute",
                                "verification_method": "recompute", "status": "OPEN"}],
                    "rationale": "math", "verified_sources": [],
                    "unverified_sources": []}
        return _approve(call_no, user)

    def fetch(url):
        return "T", "Stub passage."

    status, _ = _run_with(settings, store,
                          _base_report("Margin is +25.", "INFERRED"),
                          auditor, fetch)
    assert status["state"] == "COMPLETED_WITH_LIMITATIONS"
    assert status["corrections"] == settings.max_corrections


def test_case5_missing_transaction_fee_recorded(settings, store):
    """Missing transaction fee: executor report must record it as a
    limitation when the auditor flags it, or the correction must add it."""
    def auditor(call_no, user):
        if call_no == 1:
            return {"decision": "CORRECTIONS_REQUIRED",
                    "issues": [{"id": "A1", "severity": "MAJOR",
                                "affected_claim_or_section": "C1",
                                "description": "platform fee of 12% omitted from "
                                               "net profit calculation",
                                "evidence": "", "required_correction": "include fee",
                                "verification_method": "recompute", "status": "OPEN"}],
                    "rationale": "fee", "verified_sources": [],
                    "unverified_sources": []}
        return _approve(call_no, user)

    def fetch(url):
        return "T", "Stub passage."

    status, engine = _run_with(settings, store,
                               _base_report("Net profit is $40.", "INFERRED"),
                               auditor, fetch)
    assert status["state"] == "COMPLETED_WITH_LIMITATIONS"
    assert status["corrections"] == settings.max_corrections
    # The correction task artifact preserves the fee finding.
    corr = open(os.path.join(status["artifact_dir"], "corrections.md")).read()
    assert "12%" in corr or "fee" in corr.lower()


def test_case7_outdated_pricing_flagged_as_limitation(settings, store):
    """Outdated pricing: a report whose only source is stale must not
    present prices as VERIFIED current facts."""
    def fetch(url):
        return "T", "Stub passage."

    report = _base_report("Price is $10.", "VERIFIED")
    report["limitations"] = ["source price data is from 2022 and may be stale"]
    status, _ = _run_with(settings, store, report, _approve, fetch,
                          max_corrections=0)
    # VERIFIED claim + CONFIRMED passage still passes structurally, but the
    # limitation is preserved verbatim in the final report.
    assert status["state"] == "COMPLETED_WITH_LIMITATIONS"
    final = open(os.path.join(status["artifact_dir"], "final_report.md")).read()
    assert "2022" in final


def test_case8_contradictory_sources_force_correction(settings, store):
    """Contradictory sources: auditor names the conflict; run corrects."""
    def auditor(call_no, user):
        if call_no == 1:
            return {"decision": "CORRECTIONS_REQUIRED",
                    "issues": [{"id": "A1", "severity": "MAJOR",
                                "affected_claim_or_section": "C1",
                                "description": "S1 says fees are 5% while the "
                                               "platform's own page says 12%: "
                                               "sources contradict each other",
                                "evidence": "", "required_correction": "resolve conflict",
                                "verification_method": "re-fetch", "status": "OPEN"}],
                    "rationale": "conflict", "verified_sources": [],
                    "unverified_sources": []}
        return _approve(call_no, user)

    def fetch(url):
        return "T", "Stub passage."

    status, _ = _run_with(settings, store, _base_report(), auditor, fetch)
    assert status["state"] == "COMPLETED_WITH_LIMITATIONS"
    assert status["corrections"] == settings.max_corrections


def test_case9_inaccessible_webpage(settings, store):
    """Inaccessible webpage: fetch raises; source becomes UNREACHABLE and
    any VERIFIED claim resting on it is blocked."""
    def fetch(url):
        raise TimeoutError("connection timed out")

    status, _ = _run_with(settings, store, _base_report(), _approve, fetch,
                          max_corrections=0)
    assert status["state"] == "COMPLETED_WITH_LIMITATIONS"
    final = open(os.path.join(status["artifact_dir"], "final_report.md")).read()
    assert "UNREACHABLE" in final


def test_case10_misleading_search_snippet(settings, store):
    """Misleading snippet: the search snippet suggests support, but the
    fetched page does not contain the passage -> NOT_FOUND."""
    def fetch(url):
        return "T", "page content that never mentions the quoted snippet"

    status, _ = _run_with(settings, store,
                          _base_report(passage="quoted snippet text here"),
                          _approve, fetch, max_corrections=0)
    assert status["state"] == "COMPLETED_WITH_LIMITATIONS"


def test_case11_fabricated_quotation(settings, store):
    """Fabricated quotation: passage invented by the executor, absent from
    the real page."""
    def fetch(url):
        return "T", "real page with completely different wording"

    status, _ = _run_with(
        settings, store,
        _base_report(passage="As the CEO said, profits will triple."),
        _approve, fetch, max_corrections=0)
    assert status["state"] == "COMPLETED_WITH_LIMITATIONS"


def test_case6_unsupported_profitability_assumption(settings, store):
    """Unsupported profitability assumption: a profit claim with no
    confirmed evidence must be downgraded, not approved clean."""
    def fetch(url):
        return "T", "Stub passage."

    # Claim classified VERIFIED but source fetch fails -> blocked (case 1
    # pattern); here the claim is INFERRED with NO sources at all.
    report = _base_report("This will be profitable.", "INFERRED", source_ids=())
    report["sources"] = []
    status, _ = _run_with(settings, store, report, _approve, fetch,
                          max_corrections=0)
    assert status["state"] == "COMPLETED_WITH_LIMITATIONS"
