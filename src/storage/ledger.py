"""Persistent cumulative validation budget ledger.

One ledger per projects root (``<projects_root>/validation_ledger.json``).
It records every paid call's estimated cost -- LLM calls, search calls,
retries, failed executions -- so that a project failure, restart, or
resume can never reset the cumulative total. The cap comes from
``AR_TOTAL_VALIDATION_BUDGET`` (default $30 for the Phase 4 validation).

Costs here are ESTIMATES from reported token usage and configured prices,
exactly like project spend. The provider's bill governs; the ledger is a
guardrail, not a billing statement.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from . import artifacts as art


class ValidationLedger:
    def __init__(self, path: str, cap_usd: float):
        self.path = path
        self.cap_usd = cap_usd
        self.entries: list[dict] = []
        if os.path.exists(path):
            try:
                data = json.load(open(path, encoding="utf-8"))
                self.entries = data.get("entries", [])
            except Exception:
                self.entries = []

    @property
    def total_spent(self) -> float:
        return round(sum(e["cost_usd"] for e in self.entries), 6)

    @property
    def remaining(self) -> float:
        return round(self.cap_usd - self.total_spent, 6)

    def record(self, project_id: str, provider: str, model: str,
               cost_usd: float, kind: str) -> dict:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "project_id": project_id,
            "provider": provider,
            "model": model,
            "cost_usd": round(cost_usd, 6),
            "kind": kind,
        }
        self.entries.append(entry)
        art.atomic_write(self.path, json.dumps(
            {"cap_usd": self.cap_usd, "entries": self.entries}, indent=2))
        return entry

    def summary(self) -> dict:
        return {
            "cap_usd": self.cap_usd,
            "spent_usd": self.total_spent,
            "remaining_usd": self.remaining,
            "entries": len(self.entries),
            "path": self.path,
        }
