#!/usr/bin/env python3
"""Autonomous four-agent research system -- command line interface.

Usage:
    python main.py run "Research autonomous commodity arbitrage businesses with less than $2,000 in capital"
    python main.py status PROJECT_ID
    python main.py resume PROJECT_ID
    python main.py report PROJECT_ID
    python main.py cancel PROJECT_ID

Provider selection: if OPENAI_API_KEY is set, the OpenAI Responses API is
used for genuine research. Otherwise the deterministic stub provider runs
instead -- it proves the workflow end to end but its content is canned demo
output, NOT research. The CLI says so loudly in that case.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import Settings, load_dotenv
from src.llm.provider import LLMError, OpenAIProvider, StubProvider, default_stub_behavior
from src.orchestration.engine import Orchestrator
from src.storage.database import Store
from src.storage.ledger import ValidationLedger

# Supported local configuration: real environment variables first, then
# the repo's .env file (never overwriting real variables). No other file
# is read for credentials.
load_dotenv()


def build_orchestrator(settings: Settings, provider: str) -> tuple[Orchestrator, bool]:
    """Returns (orchestrator, is_stub)."""
    store = Store(os.path.join(settings.projects_root, "research.db"))
    if provider == "stub":
        client = StubProvider(default_stub_behavior())
        return Orchestrator(settings, store, client=client), True
    if provider == "openai":
        client = OpenAIProvider(fallback_model=settings.model_fallback,
                                timeout_s=settings.llm_timeout_s,
                                max_output_tokens=settings.max_output_tokens)
        return Orchestrator(settings, store, client=client), False
    # auto: real provider when a key exists, otherwise stub (labelled).
    if os.environ.get("OPENAI_API_KEY"):
        return Orchestrator(settings, store,
                            client=OpenAIProvider(
                                fallback_model=settings.model_fallback,
                                timeout_s=settings.llm_timeout_s,
                                max_output_tokens=settings.max_output_tokens)), False
    return Orchestrator(settings, store, client=StubProvider(default_stub_behavior())), True


def print_status(status: dict) -> None:
    print(f"Project : {status['project_id']}")
    print(f"State   : {status['state']}")
    print(f"Prompt revisions : {status['prompt_revisions']} | "
          f"Corrections : {status['corrections']} | "
          f"Tool calls : {status['tool_calls']}")
    print(f"Cost    : ${status['spent_usd']:.4f} / ${status['budget_usd']:.2f}")
    if status["failure_reason"]:
        print(f"Failure : {status['failure_reason']}")
    if status["open_critical_issues"]:
        print(f"Open CRITICAL audit issues: {status['open_critical_issues']}")
    print(f"Artifacts: {status['artifact_dir']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Autonomous research system")
    parser.add_argument("--provider", choices=["auto", "openai", "stub"],
                        default="auto", help="LLM provider (default: auto)")
    parser.add_argument("--budget", type=float, default=None,
                        help="Per-project budget in USD (default: $10)")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Start a new research project")
    run_p.add_argument("objective", help="Natural-language research objective")

    for name in ("status", "resume", "report", "cancel"):
        p = sub.add_parser(name, help=f"{name} a project")
        p.add_argument("project_id")
    sub.add_parser("ledger", help="Show cumulative validation spending")

    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
        if args.budget is not None:
            settings.budget_usd = args.budget
            settings.__post_init__()
    except ValueError as exc:
        parser.error(str(exc))
    if args.command == "ledger":
        ledger = ValidationLedger(
            os.path.join(settings.projects_root, "validation_ledger.json"),
            settings.total_validation_budget_usd)
        summary = ledger.summary()
        print(f"Cumulative validation spending: ${summary['spent_usd']:.4f} "
              f"of ${summary['cap_usd']:.2f} "
              f"(remaining ${summary['remaining_usd']:.4f}, "
              f"{summary['entries']} entries)")
        print(f"Ledger: {summary['path']}")
        return 0
    try:
        orch, is_stub = build_orchestrator(settings, args.provider)
    except LLMError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "run":
        if is_stub:
            print("NOTE: no OPENAI_API_KEY found -- running with the stub provider. "
                  "The workflow will complete end to end, but report content is "
                  "canned demo output, not genuine research.")
        project_id = orch.create_project(args.objective, budget_usd=settings.budget_usd)
        print(f"Created project {project_id}")
        status = orch.run(project_id)
        print_status(status)
        if status["state"] in ("COMPLETED", "COMPLETED_WITH_LIMITATIONS"):
            print(f"\nFinal report: {status['artifact_dir']}/final_report.md")
        print(f"DONE: project {project_id} ended in {status['state']}"
              + (f" ({status['terminal_status']})" if status.get("terminal_status") else ""))
        # Simple local completion notification: an operator-configured
        # command (no shell) receiving project id and terminal state.
        # Nothing runs unless AR_NOTIFY_CMD is set.
        notify = os.environ.get("AR_NOTIFY_CMD")
        if notify:
            try:
                subprocess.run([notify, project_id, status["state"]],
                               timeout=30, check=False)
            except Exception:
                pass
        return 0 if status["state"] == "COMPLETED" else 1

    try:
        if args.command == "status":
            print_status(orch.status(args.project_id))
            return 0
        if args.command == "resume":
            status = orch.run(args.project_id)
            print_status(status)
            return 0 if status["state"] == "COMPLETED" else 1
        if args.command == "report":
            print(orch.report_text(args.project_id))
            return 0
        if args.command == "cancel":
            orch.cancel(args.project_id)
            print_status(orch.status(args.project_id))
            return 0
    except KeyError:
        print(f"error: unknown project {args.project_id!r}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
