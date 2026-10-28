"""Workflow state machine: states, permitted transitions, terminal states.

The orchestrator may only move between states listed here, and only on a
validated structured decision (or a deterministic software event such as
budget exhaustion / cancellation). An LLM's narrative can never trigger a
transition on its own.
"""
from __future__ import annotations

from enum import Enum


class State(str, Enum):
    CREATED = "CREATED"
    PROMPT_DRAFTING = "PROMPT_DRAFTING"
    PROMPT_REVIEW = "PROMPT_REVIEW"
    PROMPT_REVISION = "PROMPT_REVISION"
    EXECUTING = "EXECUTING"
    EXECUTION_AUDIT = "EXECUTION_AUDIT"
    EXECUTION_CORRECTION = "EXECUTION_CORRECTION"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_LIMITATIONS = "COMPLETED_WITH_LIMITATIONS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


TERMINAL_STATES = frozenset({
    State.COMPLETED,
    State.COMPLETED_WITH_LIMITATIONS,
    State.FAILED,
    State.CANCELLED,
    State.BUDGET_EXHAUSTED,
})

# Every permitted edge, with the event that authorises it.
TRANSITIONS: dict[State, dict[State, str]] = {
    State.CREATED: {State.PROMPT_DRAFTING: "start", State.FAILED: "failed"},
    State.PROMPT_DRAFTING: {State.PROMPT_REVIEW: "prompt_drafted",
                            State.FAILED: "failed"},
    State.PROMPT_REVIEW: {
        State.EXECUTING: "prompt_approved",
        State.PROMPT_REVISION: "prompt_revise",
        State.FAILED: "prompt_blocked_or_limit",
    },
    State.PROMPT_REVISION: {State.PROMPT_REVIEW: "prompt_revised",
                            State.FAILED: "failed"},
    State.EXECUTING: {
        State.EXECUTION_AUDIT: "execution_finished",
        State.FAILED: "execution_failed",
    },
    State.EXECUTION_AUDIT: {
        State.FINALIZING: "audit_approved",
        State.EXECUTION_CORRECTION: "audit_corrections_required",
        State.COMPLETED_WITH_LIMITATIONS: "audit_limit_reached",
        State.FAILED: "audit_blocked",
    },
    State.EXECUTION_CORRECTION: {State.EXECUTION_AUDIT: "correction_finished",
                                 State.FAILED: "failed"},
    State.FINALIZING: {State.COMPLETED: "finalized",
                       State.COMPLETED_WITH_LIMITATIONS: "finalized_with_limitations",
                       State.FAILED: "failed"},
}

# Cancellation and budget exhaustion are software events, allowed from any
# non-terminal state. They are deliberately NOT in TRANSITIONS so that no
# agent decision can ever invoke them.
SOFTWARE_EVENTS = {"cancel", "budget_exhausted", "runtime_exceeded"}


class InvalidTransitionError(ValueError):
    pass


def validate_transition(from_state: State, to_state: State, event: str) -> None:
    """Raise InvalidTransitionError unless the edge is permitted."""
    if from_state in TERMINAL_STATES:
        raise InvalidTransitionError(
            f"cannot leave terminal state {from_state.value}")
    if event in SOFTWARE_EVENTS:
        expected = {"cancel": State.CANCELLED, "budget_exhausted": State.BUDGET_EXHAUSTED,
                    "runtime_exceeded": State.FAILED}
        if to_state != expected[event]:
            raise InvalidTransitionError(f"invalid target for {event}: {to_state}")
        return
    allowed = TRANSITIONS.get(from_state, {})
    if to_state not in allowed or allowed[to_state] != event:
        raise InvalidTransitionError(
            f"invalid transition {from_state.value} -> {to_state.value} "
            f"on event {event!r}; allowed: {allowed}")
