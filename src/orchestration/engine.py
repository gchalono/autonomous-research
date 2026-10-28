"""Deterministic orchestrator.

The orchestrator is ordinary software: it owns state transitions, revision
and correction counts, spending limits, cancellation, checkpoints and
resume. LLMs supply content (prompts, evaluations, reports, audits); they
never decide a transition, a limit, or whether a defect is resolved.

Resume semantics: before invoking an agent for a step, the orchestrator
checks whether that step's output is already stored (keyed by project +
step). If it is, the stored output is reused -- so resuming never repeats
a completed LLM call or duplicates an artifact.
"""
from __future__ import annotations

import json
import os
import time
import uuid
import math
import fcntl
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Callable, Optional

from ..agents import auditor as auditor_mod
from ..agents import creator as creator_mod
from ..agents import evaluator as evaluator_mod
from ..agents import executor as executor_mod
from ..agents.common import AgentOutputError
from ..llm.provider import LLMError, ProviderControlFlowError
from ..config import Settings
from ..models.contracts import (AuditDecision, AuditReport, CorrectionTask,
                                EvaluationDecision, ExecutionReport,
                                IssueSeverity, PromptSpec, AuditIssue, IssueStatus,
                                VerificationStatus)
from ..storage import artifacts as art
from ..storage.database import Store
from ..storage.ledger import ValidationLedger
from ..tools.base import ToolRegistry, ToolResult, default_registry
from ..tools.retrieval import fetch_url
from . import correction as correction_mod
from .states import (State, TERMINAL_STATES, InvalidTransitionError,
                     validate_transition)


class BudgetExhausted(ProviderControlFlowError):
    pass


class RunStopped(ProviderControlFlowError):
    pass


class RunFailed(ProviderControlFlowError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def new_project_id() -> str:
    return uuid.uuid4().hex[:12]


class Orchestrator:
    def __init__(self, settings: Settings, store: Store,
                 client=None, registry: Optional[ToolRegistry] = None,
                 fetch_fn: Callable = fetch_url):
        self.settings = settings
        self.store = store
        self.client = client
        self.registry = registry or default_registry()
        self.fetch_fn = fetch_fn
        self.models = settings.models
        # Cumulative ledger: survives failures, restarts, and resumes.
        self.ledger = ValidationLedger(
            os.path.join(settings.projects_root, "validation_ledger.json"),
            settings.total_validation_budget_usd)

    # ------------------------------------------------------------ helpers
    def _project(self, project_id: str) -> dict:
        proj = self.store.get_project(project_id)
        if proj is None:
            raise KeyError(f"unknown project {project_id}")
        return proj

    def _log(self, project_id: str, event: dict) -> None:
        """Structured run log (JSONL). Never logs prompts, keys, or secrets:
        only ids, stages, models, token counts, costs, and transitions."""
        entry = {"ts": datetime.now(timezone.utc).isoformat(),
                 "project_id": project_id}
        entry.update(event)
        try:
            art.append_line(self.settings.projects_root, project_id,
                            "run_log.jsonl", json.dumps(entry))
        except Exception:
            pass  # logging must never break a run

    def _transition(self, project_id: str, from_state: State, to_state: State,
                    event: str, detail: str = "", counters: dict | None = None) -> None:
        validate_transition(from_state, to_state, event)
        self.store.transition(project_id, from_state.value, to_state.value, event, detail, counters)
        self._log(project_id, {"type": "transition", "event": event,
                               "from": from_state.value, "to": to_state.value,
                               "detail": detail[:200]})

    def _check_cancel(self, project_id: str, state: State) -> bool:
        if self.store.get_project(project_id)["cancel_requested"]:
            self._transition(project_id, state, State.CANCELLED, "cancel",
                             "cancellation requested")
            return True
        return False

    def _check_runtime(self, project_id: str, state: State) -> bool:
        """Fail the run when the wall-clock runtime limit is exceeded.
        Returns True if the limit fired."""
        proj = self.store.get_project(project_id)
        try:
            created = datetime.fromisoformat(proj["created_at"])
        except Exception:
            return False
        elapsed = (datetime.now(timezone.utc) - created).total_seconds()
        if elapsed > self.settings.max_runtime_s:
            reason = (f"runtime limit exceeded ({elapsed:.0f}s > "
                      f"{self.settings.max_runtime_s}s)")
            self.store.update_counters(project_id, failure_reason=reason)
            # Software runtime events are valid from every non-terminal phase.
            self._transition(project_id, state, State.FAILED, "runtime_exceeded",
                             reason)
            self._log(project_id, {"type": "runtime_limit",
                                   "elapsed_s": round(elapsed, 1)})
            return True
        return False

    def _cost_cb(self, project_id: str):
        def cb(model: str, in_tokens: int, out_tokens: int,
               preflight: bool = False) -> None:
            proj = self.store.get_project(project_id)
            if preflight:
                self._guard_running(project_id)
                # Refuse an estimate that would breach either budget,
                # including the project's first call.
                estimate = self.settings.estimate_cost_usd(
                    model, in_tokens, out_tokens)
                if self.ledger.total_spent + estimate > self.ledger.cap_usd:
                    self._log(project_id, {"type": "preflight_rejected",
                                           "reason": "cumulative_cap",
                                           "estimate_usd": round(estimate, 6),
                                           "ledger_spent_usd": self.ledger.total_spent})
                    raise BudgetExhausted(
                        f"preflight budget check: estimated call cost "
                        f"${estimate:.4f} would exceed cumulative validation "
                        f"budget (${self.ledger.total_spent:.4f} spent of "
                        f"${self.ledger.cap_usd:.2f})")
                if proj["spent_usd"] + estimate > proj["budget_usd"]:
                    raise BudgetExhausted("preflight budget check: estimated call cost "
                                          "would exceed remaining project budget")
                requests = self.store.load_output(project_id, 'model_request_count') or {'count': 0}
                if requests['count'] >= self.settings.max_model_requests:
                    raise RunFailed('model request limit reached; no further request dispatched')
                self.store.save_output(project_id, 'model_request_count', {'count': requests['count'] + 1})
                return
            cost = self.settings.estimate_cost_usd(model, in_tokens, out_tokens)
            self.store.add_spend(project_id, cost)
            self.ledger.record(project_id, "openai", model, cost, "llm_call", usage={
                "input_tokens": in_tokens, "output_tokens": out_tokens,
                "observed_usage": getattr(self.client, "last_usage", None),
                "response_id": getattr(self.client, "last_response_id", None)})
            self._log(project_id, {"type": "llm_call", "model": model,
                                   "input_tokens": in_tokens,
                                   "output_tokens": out_tokens,
                                   "estimated_cost_usd": round(cost, 6),
                                   "response_id": getattr(
                                       self.client, "last_response_id", None)})
        return cb

    def _cached(self, project_id: str, step_key: str, fn: Callable):
        """Return a stored step output, or compute, store and return it."""
        stored = self.store.load_output(project_id, step_key)
        if stored is not None:
            return stored
        result = fn()
        payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
        self.store.save_output(project_id, step_key, payload)
        return payload

    def _tool_runner(self, project_id: str, namespace: str | None = None):
        def runner(tool, arguments: dict, call_key: str | None = None):
            result_key = f"{namespace}_tool_{call_key}" if namespace and call_key is not None else None
            if result_key is not None:
                cached = self.store.load_output(project_id, result_key)
                if cached is not None:
                    if cached['tool'] != tool.name or cached['arguments'] != arguments:
                        raise RunFailed("native tool checkpoint identity mismatch")
                    return ToolResult(**cached['result'])
            self._guard_running(project_id)
            if len(self.store.list_tool_calls(project_id)) >= self.settings.max_tool_calls:
                raise RunFailed('tool-call limit reached; no further tool dispatched')
            charge = (self.settings.tavily_cost_per_search
                      if tool.name == "web_search" else 0.0)
            proj = self._project(project_id)
            if (proj["spent_usd"] + charge > proj["budget_usd"]
                    or self.ledger.total_spent + charge > self.ledger.cap_usd):
                raise BudgetExhausted("tool preflight would exceed project or cumulative budget")
            result = tool.invoke(arguments)
            self.store.record_tool_call(project_id, tool.name, arguments,
                                        result.ok, result.preview(), charge,
                                        result_key=result_key,
                                        result_payload={'tool': tool.name, 'arguments': arguments,
                                                        'result': asdict(result)})
            # Search-tool charges: recorded only when a per-search price is
            # configured; otherwise calls are counted but billed nothing
            # (inventing a price would corrupt cost accounting).
            if tool.name == "web_search" and self.settings.tavily_cost_per_search > 0:
                self.ledger.record(project_id, "tavily", "web_search",
                                   self.settings.tavily_cost_per_search,
                                   "search_call")
                self._log(project_id, {"type": "search_call",
                                       "cost_usd": self.settings.tavily_cost_per_search})
            return result
        return runner

    # ------------------------------------------------------------ lifecycle
    def create_project(self, objective: str, budget_usd: Optional[float] = None) -> str:
        budget = self.settings.budget_usd if budget_usd is None else budget_usd
        if not math.isfinite(budget) or budget < 0:
            raise ValueError("budget must be finite and nonnegative")
        project_id = new_project_id()
        self.store.create_project(
            project_id, objective,
            self.settings.budget_usd if budget_usd is None else budget_usd)
        art.write_text(self.settings.projects_root, project_id, "objective.md",
                       f"# Objective\n\n{objective}\n")
        return project_id

    def cancel(self, project_id: str) -> dict:
        proj = self._project(project_id)
        if State(proj["state"]) in TERMINAL_STATES:
            return self.status(project_id)
        self.store.request_cancel(project_id)
        return self.status(project_id)

    @staticmethod
    def terminal_status(state: str, failure_reason: str | None) -> str | None:
        """Spec section 15.1 completion labels, derived from persisted state
        (never from an agent's self-report)."""
        mapping = {
            "COMPLETED": "COMPLETED_APPROVED",
            "COMPLETED_WITH_LIMITATIONS": "COMPLETED_WITH_LIMITATIONS",
            "CANCELLED": "CANCELLED",
            "BUDGET_EXHAUSTED": "BUDGET_EXHAUSTED",
        }
        if state in mapping:
            return mapping[state]
        if state == "FAILED":
            reason = (failure_reason or "").lower()
            if "prompt" in reason:
                return "FAILED_VALIDATION"
            return "FAILED_EXECUTION"
        return None

    def status(self, project_id: str) -> dict:
        proj = self._project(project_id)
        issues = self.store.list_issues(project_id)
        open_critical = [i for i in issues
                         if i["severity"] == "CRITICAL" and i["status"] not in ("RESOLVED", "SUPERSEDED")]
        return {
            "project_id": project_id,
            "objective": proj["objective"],
            "state": proj["state"],
            "terminal_status": self.terminal_status(proj["state"],
                                                    proj["failure_reason"]),
            "prompt_revisions": proj["prompt_revisions"],
            "corrections": proj["corrections"],
            "spent_usd": round(proj["spent_usd"], 4),
            "budget_usd": proj["budget_usd"],
            "failure_reason": proj["failure_reason"],
            "open_critical_issues": len(open_critical),
            "total_issues": len(issues),
            "tool_calls": len(self.store.list_tool_calls(project_id)),
            "events": len(self.store.list_events(project_id)),
            "artifact_dir": art.project_dir(self.settings.projects_root, project_id),
        }

    def report_text(self, project_id: str) -> str:
        root = self.settings.projects_root
        if art.artifact_exists(root, project_id, "final_report.md"):
            return art.read_text(root, project_id, "final_report.md")
        if art.artifact_exists(root, project_id, "execution_report.md"):
            return art.read_text(root, project_id, "execution_report.md")
        return "No report has been produced yet for this project."

    # ------------------------------------------------------------ main loop
    def _guard_running(self, project_id: str):
        state = State(self._project(project_id)["state"])
        if state in TERMINAL_STATES:
            raise RunStopped()
        if self._check_cancel(project_id, state) or self._check_runtime(project_id, state):
            raise RunStopped()

    def run(self, project_id: str) -> dict:
        # Serialize the projects root, including budget preflight and ledger writes.
        # flock works on the supported Linux/macOS CLI platforms and releases on crash.
        os.makedirs(self.settings.projects_root, exist_ok=True)
        with open(os.path.join(self.settings.projects_root, ".run.lock"), "a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("another research run is active in this projects root") from exc
            self._reconcile_spend()
            return self._run_locked(project_id)

    def _reconcile_spend(self):
        # SQLite and the JSON ledger cannot share one transaction. Recover a
        # crash between their writes by retaining the greater recorded total
        # for each project; never reset either budget on restart.
        self.ledger.total_spent  # refresh retained entries
        ledger_spend = {}
        for entry in self.ledger.entries:
            pid = entry["project_id"]
            ledger_spend[pid] = ledger_spend.get(pid, 0.0) + entry["cost_usd"]
        for row in self.store.list_project_spend():
            recorded = ledger_spend.get(row["id"], 0.0)
            delta = row["spent_usd"] - recorded
            if delta > 0.000001:
                self.ledger.record(row["id"], "recovery", "unknown", delta, "spend_reconciliation")
            elif delta < -0.000001:
                self.store.add_spend(row["id"], -delta)

    def _run_locked(self, project_id: str) -> dict:
        """Run (or resume) a project to a terminal state. Returns status.

        Transient provider errors (timeout / rate limit / temporary
        overload) do NOT fail the run: the project stays in its current
        non-terminal state and the returned status carries
        ``transient_error`` so a later resume can continue. Permanent
        failures still terminate as FAILED with artifacts preserved.
        """
        if self.client is None:
            raise RuntimeError("no LLM client configured")
        cost_cb = self._cost_cb(project_id)
        if getattr(self.client, "manages_costs", False):
            self.client.request_cost_cb = cost_cb
        transient_error = None
        try:
            while True:
                proj = self._project(project_id)
                state = State(proj["state"])
                if state in TERMINAL_STATES:
                    break
                if self._check_cancel(project_id, state):
                    break
                if self._check_runtime(project_id, state):
                    break
                handler = {
                    State.CREATED: self._step_created,
                    State.PROMPT_DRAFTING: self._step_draft,
                    State.PROMPT_REVIEW: self._step_review,
                    State.PROMPT_REVISION: self._step_revise,
                    State.EXECUTING: self._step_execute,
                    State.EXECUTION_AUDIT: self._step_audit,
                    State.EXECUTION_CORRECTION: self._step_correct,
                    State.FINALIZING: self._step_finalize,
                }[state]
                handler(project_id, cost_cb)
        except RunStopped:
            pass
        except BudgetExhausted as exc:
            proj = self._project(project_id)
            state = State(proj["state"])
            if state not in TERMINAL_STATES:
                self.store.update_counters(project_id, failure_reason=str(exc))
                self._transition(project_id, state, State.BUDGET_EXHAUSTED,
                                 "budget_exhausted", str(exc))
        except LLMError as exc:
            # Transient: keep the project resumable, record nothing terminal.
            self._log(project_id, {"type": "transient_error",
                                   "error": str(exc)[:300]})
            transient_error = str(exc)
        except (AgentOutputError, RunFailed) as exc:
            proj = self._project(project_id)
            state = State(proj["state"])
            reason = exc.reason if isinstance(exc, RunFailed) else str(exc)
            if state not in TERMINAL_STATES:
                self.store.update_counters(project_id, failure_reason=reason)
                event = {
                    State.PROMPT_REVIEW: "prompt_blocked_or_limit",
                    State.EXECUTING: "execution_failed",
                    State.EXECUTION_AUDIT: "audit_blocked",
                }.get(state, "failed")
                self._transition(project_id, state, State.FAILED, event, reason)
        except InvalidTransitionError:
            raise
        self._write_metadata(project_id)
        result = self.status(project_id)
        if transient_error is not None:
            result["transient_error"] = transient_error
        return result

    # ------------------------------------------------------------ steps
    def _step_created(self, project_id: str, cost_cb) -> None:
        self._transition(project_id, State.CREATED, State.PROMPT_DRAFTING, "start")

    def _current_prompt(self, project_id: str) -> PromptSpec:
        proj = self._project(project_id)
        version = proj["prompt_revisions"] + 1
        payload = self.store.load_output(project_id, f"prompt_v{version}")
        if payload is None:
            raise RunFailed(f"prompt version {version} not found; cannot resume")
        return PromptSpec.model_validate(payload)

    def _step_draft(self, project_id: str, cost_cb) -> None:
        proj = self._project(project_id)
        version = proj["prompt_revisions"] + 1
        payload = self._cached(
            project_id, f"prompt_v{version}",
            lambda: creator_mod.create_prompt(
                self.client, self.models["creator"], proj["objective"], cost_cb=cost_cb,
                estimated_output_tokens=self.settings.estimated_output_tokens))
        spec = PromptSpec.model_validate(payload)
        spec.revision_number = version  # normalize: the version is the engine's, not the LLM's
        self.store.save_output(project_id, f"prompt_v{version}",
                               spec.model_dump(mode="json"))
        art.write_json(self.settings.projects_root, project_id,
                       f"prompt_v{version}.json", spec.model_dump(mode="json"))
        art.write_text(self.settings.projects_root, project_id,
                       f"prompt_v{version}.md", spec.execution_prompt)
        self._transition(project_id, State.PROMPT_DRAFTING, State.PROMPT_REVIEW,
                         "prompt_drafted", f"revision {version}")

    def _step_review(self, project_id: str, cost_cb) -> None:
        proj = self._project(project_id)
        spec = self._current_prompt(project_id)
        version = spec.revision_number
        payload = self._cached(
            project_id, f"eval_v{version}",
            lambda: evaluator_mod.evaluate_prompt(
                self.client, self.models["evaluator"], proj["objective"], spec,
                cost_cb=cost_cb,
                estimated_output_tokens=self.settings.estimated_output_tokens))
        from ..models.contracts import PromptEvaluation
        evaluation = PromptEvaluation.model_validate(payload)
        art.write_json(self.settings.projects_root, project_id,
                       f"prompt_evaluation_v{version}.json",
                       evaluation.model_dump(mode="json"))
        art.write_json(self.settings.projects_root, project_id,
                       "prompt_evaluation.json", evaluation.model_dump(mode="json"))
        if evaluation.decision == EvaluationDecision.APPROVE:
            art.write_text(self.settings.projects_root, project_id,
                           "approved_prompt.md", spec.execution_prompt)
            self._transition(project_id, State.PROMPT_REVIEW, State.EXECUTING,
                             "prompt_approved")
        elif evaluation.decision == EvaluationDecision.REVISE:
            if proj["prompt_revisions"] >= self.settings.max_prompt_revisions:
                reason = ("prompt revision limit reached "
                          f"({self.settings.max_prompt_revisions}); last issues: "
                          + "; ".join(evaluation.required_revisions))
                self.store.update_counters(project_id, failure_reason=reason)
                self._transition(project_id, State.PROMPT_REVIEW, State.FAILED,
                                 "prompt_blocked_or_limit", reason)
            else:
                self._transition(project_id, State.PROMPT_REVIEW, State.PROMPT_REVISION,
                                 "prompt_revise",
                                 "; ".join(evaluation.required_revisions),
                                 counters={"prompt_revisions": proj["prompt_revisions"] + 1})
        else:  # BLOCKED
            reason = "prompt evaluator blocked: " + "; ".join(
                evaluation.critical_issues or ["no reason given"])
            self.store.update_counters(project_id, failure_reason=reason)
            self._transition(project_id, State.PROMPT_REVIEW, State.FAILED,
                             "prompt_blocked_or_limit", reason)

    def _step_revise(self, project_id: str, cost_cb) -> None:
        proj = self._project(project_id)
        version = proj["prompt_revisions"] + 1  # revisions already incremented
        prev_version = version - 1
        prev = PromptSpec.model_validate(
            self.store.load_output(project_id, f"prompt_v{prev_version}"))
        evaluation = self.store.load_output(project_id, f"eval_v{prev_version}")
        required = evaluation["required_revisions"] if evaluation else []
        payload = self._cached(
            project_id, f"prompt_v{version}",
            lambda: creator_mod.create_prompt(
                self.client, self.models["creator"], proj["objective"],
                previous=prev, required_revisions=required, cost_cb=cost_cb,
                estimated_output_tokens=self.settings.estimated_output_tokens))
        spec = PromptSpec.model_validate(payload)
        spec.revision_number = version
        self.store.save_output(project_id, f"prompt_v{version}",
                               spec.model_dump(mode="json"))
        art.write_json(self.settings.projects_root, project_id,
                       f"prompt_v{version}.json", spec.model_dump(mode="json"))
        art.write_text(self.settings.projects_root, project_id,
                       f"prompt_v{version}.md", spec.execution_prompt)
        self._transition(project_id, State.PROMPT_REVISION, State.PROMPT_REVIEW,
                         "prompt_revised", f"revision {version}")

    def _step_execute(self, project_id: str, cost_cb) -> None:
        self._run_execution(project_id, cost_cb, correction=None)
        self._transition(project_id, State.EXECUTING, State.EXECUTION_AUDIT,
                         "execution_finished")

    def _run_execution(self, project_id: str, cost_cb,
                       correction: Optional[CorrectionTask] = None,
                       full_reexecution: bool = False) -> ExecutionReport:
        proj = self._project(project_id)
        spec = self._current_prompt(project_id)
        attempt = proj["corrections"]  # 0 = initial, >=1 = after corrections
        step_key = f"execution_{attempt}"
        stored = self.store.load_output(project_id, step_key)
        if stored is not None:
            report = ExecutionReport.model_validate(stored)
        else:
            boundary_key = f"execution_{attempt}_provenance_start"
            if self.store.load_output(project_id, boundary_key) is None:
                previous_boundary = self.store.load_output(
                    project_id, f"execution_{attempt - 1}_provenance_start") or {}
                after = (max((t["id"] for t in self.store.list_tool_calls(project_id)), default=0)
                         if full_reexecution else previous_boundary.get("after_tool_call", 0))
                self.store.save_output(project_id, boundary_key, {"after_tool_call": after})
            previous_report = None
            if correction is not None and attempt > 0:
                prev = self.store.load_output(project_id, f"execution_{attempt - 1}")
                if prev is not None:
                    previous_report = ExecutionReport.model_validate(prev)
            # Native function calling whenever the client supports it; the
            # legacy JSON-step loop is kept for clients that do not (stubs).
            tool_client = (self.client
                           if getattr(self.client, "supports_native_tools", False)
                           else None)
            report = executor_mod.run_execution(
                self.client, self.models["executor"], spec, self.registry,
                max_iterations=self.settings.max_tool_iterations,
                cost_cb=cost_cb, tool_runner=self._tool_runner(project_id),
                correction=correction, previous_report=previous_report,
                full_reexecution=full_reexecution,
                estimated_output_tokens=self.settings.estimated_output_tokens,
                tool_client=tool_client,
                checkpointed_tool_runner=self._tool_runner(project_id, step_key),
                checkpoint=self.store.load_output(project_id, step_key + "_checkpoint"),
                save_checkpoint=lambda data: self.store.save_output(
                    project_id, step_key + "_checkpoint", data))
            self.store.save_output(project_id, step_key, report.model_dump(mode="json"))
        art.write_json(self.settings.projects_root, project_id,
                       f"execution_report_{attempt}.json", report.model_dump(mode="json"))
        art.write_text(self.settings.projects_root, project_id,
                       "execution_report.md", self._render_execution(report))
        art.write_json(self.settings.projects_root, project_id,
                       "sources.json",
                       {"sources": [s.model_dump(mode="json") for s in report.sources]})
        return report

    def _step_audit(self, project_id: str, cost_cb) -> None:
        proj = self._project(project_id)
        spec = self._current_prompt(project_id)
        attempt = proj["corrections"]
        report = ExecutionReport.model_validate(
            self.store.load_output(project_id, f"execution_{attempt}"))
        def guarded_fetch(url):
            self._guard_running(project_id)
            return self.fetch_fn(url)
        stored_verification = self.store.load_output(project_id, f"verification_{attempt}")
        independent_evidence = self.store.load_output(project_id, f"verification_evidence_{attempt}") or {}
        if stored_verification is None:
            verification = auditor_mod.verify_sources(
                report, guarded_fetch, max_sources=self.settings.max_sources_to_verify,
                evidence_sink=independent_evidence)
            self.store.save_output(project_id, f"verification_evidence_{attempt}", independent_evidence)
            self.store.save_output(project_id, f"verification_{attempt}",
                                   {sid: value.value for sid, value in verification.items()})
        else:
            verification = {sid: VerificationStatus(value)
                            for sid, value in stored_verification.items()}
        # Persist the code-level verification facts on the sources AND write
        # them back, so the final report shows the verified statuses instead
        # of the executor's original UNCHECKED values.
        for source in report.sources:
            if source.id in verification:
                source.verification_status = verification[source.id]
        self.store.save_output(project_id, f"execution_{attempt}",
                               report.model_dump(mode="json"))
        art.write_json(self.settings.projects_root, project_id,
                       f"execution_report_{attempt}.json", report.model_dump(mode="json"))
        art.write_json(self.settings.projects_root, project_id,
                       "sources.json",
                       {"sources": [s.model_dump(mode="json") for s in report.sources]})
        # Deterministic claim-to-evidence analysis (see claim_check.py):
        # passage presence alone never proves a claim, so code enforces the
        # structural requirements (VERIFIED needs a CONFIRMED source, cited
        # ids must exist, derivations need evidence) regardless of what the
        # auditor LLM concludes.
        from . import claim_check as claim_check_mod
        boundary = self.store.load_output(project_id, f"execution_{attempt}_provenance_start") or {}
        code_issues = claim_check_mod.analyze_claim_support(
            report, verification, [t for t in self.store.list_tool_calls(project_id)
                                   if t["id"] > boundary.get("after_tool_call", 0)])
        previous_issues = [AuditIssue.model_validate(row)
                           for row in self.store.list_issues(project_id)]
        payload = self._cached(
            project_id, f"audit_{attempt}",
            lambda: auditor_mod.audit_execution(
                self.client, self.models["auditor"], proj["objective"], spec,
                report, verification, cost_cb=cost_cb,
                estimated_output_tokens=self.settings.estimated_output_tokens,
                previous_issues=[i.model_dump(mode="json") for i in previous_issues],
                independent_evidence=independent_evidence,
                calculation_evidence=[{'arguments': json.loads(t['arguments_json']),
                                       'output': t['output_preview']}
                                      for t in self.store.list_tool_calls(project_id)
                                      if t['id'] > boundary.get('after_tool_call', 0)
                                      and t['tool'] == 'calculate' and t['ok']]))
        audit = AuditReport.model_validate(payload)
        # The audit's verified/unverified source lists are facts established
        # by code re-fetching, not LLM assertions: overwrite them.
        audit.verified_sources = [sid for sid, st in verification.items()
                                  if st.value == "CONFIRMED"]
        audit.unverified_sources = [sid for sid, st in verification.items()
                                    if st.value != "CONFIRMED"]
        # Code-owned issues resolve only when re-analysis no longer reproduces
        # the same defect. LLM-owned issues require explicit auditor resolution.
        current_code_ids = {i.id for i in code_issues}
        prior = [i.model_copy(update={"status": IssueStatus.RESOLVED})
                 if i.id.startswith("CC-") and i.id not in current_code_ids else i
                 for i in previous_issues]
        llm_audit = audit.model_copy(update={"issues": [i for i in audit.issues
                                                       if not i.id.startswith("CC-")]})
        merged = {i.id: i for i in correction_mod.apply_audit_to_issues(llm_audit, prior)}
        merged.update({i.id: i for i in code_issues})
        blocking = (IssueSeverity.CRITICAL, IssueSeverity.MAJOR)
        has_blocking = any(i.severity in blocking and correction_mod.is_unresolved(i)
                           for i in merged.values())
        effective = audit.decision
        if effective == AuditDecision.APPROVE and has_blocking:
            effective = AuditDecision.CORRECTIONS_REQUIRED
        audit = audit.model_copy(update={"decision": effective, "issues": list(merged.values())})
        for issue in audit.issues:
            self.store.upsert_issue(project_id, issue.model_dump(mode="json"))
        # Persist the effective audit, not the raw model approval. It is also
        # the checkpoint used by correction routing and final report rendering.
        self.store.save_output(project_id, f"audit_{attempt}", audit.model_dump(mode="json"))
        art.write_json(self.settings.projects_root, project_id,
                       f"audit_report_{attempt}.json", audit.model_dump(mode="json"))
        art.write_json(self.settings.projects_root, project_id,
                       "audit_report.json", audit.model_dump(mode="json"))
        if effective == AuditDecision.APPROVE:
            self._transition(project_id, State.EXECUTION_AUDIT, State.FINALIZING,
                             "audit_approved")
        elif effective in (AuditDecision.CORRECTIONS_REQUIRED, AuditDecision.INCONCLUSIVE):
            if proj["corrections"] >= self.settings.max_corrections:
                unresolved = [i for i in audit.issues
                              if correction_mod.is_unresolved(i) and
                              i.severity in (IssueSeverity.CRITICAL, IssueSeverity.MAJOR)]
                detail = ("correction limit reached; unresolved: "
                          + "; ".join(i.id for i in unresolved))
                # A limitations outcome still owes the user a final report
                # (previously this path transitioned without writing one).
                final = self._render_final(
                    proj, report, audit,
                    [i.model_dump(mode="json") for i in unresolved])
                art.write_text(self.settings.projects_root, project_id,
                               "final_report.md", final)
                self._transition(project_id, State.EXECUTION_AUDIT,
                                 State.COMPLETED_WITH_LIMITATIONS,
                                 "audit_limit_reached", detail)
            else:
                task = correction_mod.build_correction_task(audit)
                art.write_json(self.settings.projects_root, project_id,
                               "correction_task.json",
                               task.model_dump(mode="json"))
                art.write_text(self.settings.projects_root, project_id,
                               "corrections.md",
                               self._render_correction(task, audit))
                self.store.save_output(project_id, f"correction_{attempt}",
                                       task.model_dump(mode="json"))
                self._transition(project_id, State.EXECUTION_AUDIT,
                                 State.EXECUTION_CORRECTION,
                                 "audit_corrections_required",
                                 "; ".join(task.issue_ids),
                                 counters={"corrections": proj["corrections"] + 1})
        else:  # BLOCKED
            reason = "audit blocked: " + audit.rationale
            self.store.update_counters(project_id, failure_reason=reason)
            self._transition(project_id, State.EXECUTION_AUDIT, State.FAILED,
                             "audit_blocked", reason)

    def _step_correct(self, project_id: str, cost_cb) -> None:
        proj = self._project(project_id)
        attempt = proj["corrections"] - 1  # correction task index just created
        task_payload = self.store.load_output(project_id, f"correction_{attempt}")
        task = CorrectionTask.model_validate(task_payload) if task_payload else None
        # Full re-execution (spec 10.2) when the last audit found the
        # methodology or evidence base itself invalid -- previously this
        # check existed but was never wired into the workflow.
        last_audit_payload = self.store.load_output(project_id, f"audit_{attempt}")
        full = False
        if last_audit_payload is not None:
            last_audit = AuditReport.model_validate(last_audit_payload)
            full = correction_mod.needs_full_reexecution(last_audit)
        if full:
            self._run_execution(project_id, cost_cb, correction=None,
                                full_reexecution=True)
        else:
            self._run_execution(project_id, cost_cb, correction=task)
        self._transition(project_id, State.EXECUTION_CORRECTION, State.EXECUTION_AUDIT,
                         "correction_finished")

    def _step_finalize(self, project_id: str, cost_cb) -> None:
        proj = self._project(project_id)
        attempt = proj["corrections"]
        report = ExecutionReport.model_validate(
            self.store.load_output(project_id, f"execution_{attempt}"))
        audit = AuditReport.model_validate(
            self.store.load_output(project_id, f"audit_{attempt}"))
        issues = self.store.list_issues(project_id)
        unresolved = [i for i in issues if i["status"] not in ("RESOLVED", "SUPERSEDED")
                      and i["severity"] in ("CRITICAL", "MAJOR")]
        final = self._render_final(proj, report, audit, unresolved)
        art.write_text(self.settings.projects_root, project_id, "final_report.md", final)
        limited = bool(unresolved or report.limitations or report.unresolved_dependencies)
        self._transition(project_id, State.FINALIZING,
                         State.COMPLETED_WITH_LIMITATIONS if limited else State.COMPLETED,
                         "finalized_with_limitations" if limited else "finalized")

    # ------------------------------------------------------------ rendering
    def _render_execution(self, report: ExecutionReport) -> str:
        lines = ["# Execution Report\n", report.executive_summary, "\n## Findings\n"]
        for f in report.findings:
            lines.append(f"### {f.title}\n{f.text}\n")
        lines.append("## Claims\n")
        for c in report.claims:
            lines.append(f"- [{c.id}] ({c.classification.value}) {c.text} "
                         f"(sources: {', '.join(c.source_ids)})")
        lines.append("\n## Sources\n")
        for s in report.sources:
            lines.append(f"- [{s.id}] {s.title} -- {s.url} "
                         f"({s.verification_status.value})")
        if report.limitations:
            lines.append("\n## Limitations\n" + "\n".join(f"- {x}" for x in report.limitations))
        if report.unresolved_dependencies:
            lines.append("\n## Unresolved dependencies\n" +
                         "\n".join(f"- {x}" for x in report.unresolved_dependencies))
        return "\n".join(lines) + "\n"

    def _render_correction(self, task: CorrectionTask, audit: AuditReport) -> str:
        lines = ["# Correction Task\n", "## Required changes\n"]
        lines += [f"- {c}" for c in task.required_changes]
        lines.append("\n## Audit issues\n")
        for i in audit.issues:
            lines.append(f"- [{i.id}] {i.severity.value}: {i.description} "
                         f"-- correction: {i.required_correction}")
        return "\n".join(lines) + "\n"

    def _render_final(self, proj: dict, report: ExecutionReport,
                      audit: AuditReport, unresolved: list[dict]) -> str:
        lines = [
            "# Final Report\n",
            f"**Objective:** {proj['objective']}\n",
            f"**Completion:** {'COMPLETED_WITH_LIMITATIONS' if unresolved or report.limitations or report.unresolved_dependencies or audit.decision != AuditDecision.APPROVE else 'COMPLETED_APPROVED'}\n",
            "## 1. Executive summary\n", report.executive_summary,
            "\n## 2. Research findings\n",
        ]
        for f in report.findings:
            lines.append(f"### {f.title}\n{f.text}\n")
        lines.append("## 3. Evidence and citations\n")
        for s in report.sources:
            lines.append(f"- [{s.id}] {s.title} -- {s.url} "
                         f"({s.verification_status.value})")
            if s.passage:
                lines.append(f"  Passage: {s.passage[:300]}")
        lines.append("\n## 4. Analysis\n")
        for c in report.claims:
            lines.append(f"- [{c.id}] ({c.classification.value}) {c.text}")
        lines.append("\n## 5. Conclusions\n" + report.executive_summary)
        lines.append("\n## 6. Important limitations\n" +
                     ("\n".join(f"- {x}" for x in report.limitations)
                      if report.limitations else "- None recorded.") +
                     ("\nUnresolved dependencies:\n" + "\n".join(
                         f"- {x}" for x in report.unresolved_dependencies)
                      if report.unresolved_dependencies else ""))
        lines.append("\n## 7. Audit outcome\n" +
                     f"Decision: {audit.decision.value}\n{audit.rationale}")
        lines.append("\n## 8. Unresolved issues\n" +
                     ("\n".join(f"- [{i['id']}] {i['severity']}: {i['description']}"
                                for i in unresolved)
                      if unresolved else "- None."))
        lines.append("\n## 9. Recommended next actions\n"
                     "- Review the findings and sources above before acting on them.\n"
                     "- Resolve any unresolved issues listed in section 8.\n")
        # Appendix: per-claim verification record (spec section 9). Each
        # claim's classification, cited sources, and code verification
        # result are preserved together so a reader can audit every
        # material claim without re-running the pipeline.
        lines.append("\n## 10. Claim verification detail\n")
        status_by_id = {s.id: s.verification_status.value for s in report.sources}
        for c in report.claims:
            cited = ", ".join(f"{sid} ({status_by_id.get(sid, 'MISSING')})"
                              for sid in c.source_ids) or "no sources cited"
            lines.append(f"- [{c.id}] {c.classification.value}: {c.text}\n"
                         f"  Evidence: {cited}")
            if c.calculation_expressions:
                lines.append("  Calculations: " + "; ".join(c.calculation_expressions))
        return "\n".join(lines) + "\n"

    def _write_metadata(self, project_id: str) -> None:
        proj = self._project(project_id)
        tool_calls = self.store.list_tool_calls(project_id)
        art.write_json(self.settings.projects_root, project_id, "run_metadata.json", {
            "project_id": project_id,
            "objective": proj["objective"],
            "state": proj["state"],
            "terminal_status": self.terminal_status(proj["state"],
                                                    proj["failure_reason"]),
            "prompt_revisions": proj["prompt_revisions"],
            "corrections": proj["corrections"],
            "spent_usd": proj["spent_usd"],
            "budget_usd": proj["budget_usd"],
            "failure_reason": proj["failure_reason"],
            # Models that actually executed (fallback included when used);
            # empty for stub runs, which do not hit a provider.
            "models_used": sorted(getattr(self.client, "models_used", set())),
            "configured_models": dict(self.models),
            "tool_calls": len(tool_calls),
            "model_requests": (self.store.load_output(project_id, 'model_request_count') or {}).get('count', 0),
            "search_calls": len([t for t in tool_calls if t["tool"] == "web_search"]),
            "events": self.store.list_events(project_id),
        })
