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
import math
import fcntl
from datetime import datetime, timezone

from . import artifacts as art


class ValidationLedger:
    def __init__(self, path: str, cap_usd: float):
        self.path = path
        self.cap_usd = cap_usd
        self.entries: list[dict] = []
        self._reload()

    def _reload(self):
        if not os.path.exists(self.path):
            self.entries = []
            return
        # Corrupt accounting must stop spending, never silently reset it.
        with open(self.path, encoding="utf-8") as fh:
            data = json.load(fh)
        entries = data["entries"]
        if not isinstance(entries, list) or any(
                not isinstance(e, dict) or not isinstance(e.get("cost_usd"), (int, float))
                or not math.isfinite(e["cost_usd"]) or e["cost_usd"] < 0 for e in entries):
            raise ValueError("invalid validation ledger; restore accounting before spending")
        self.entries = entries

    @property
    def total_spent(self) -> float:
        self._reload()
        return round(sum(e["cost_usd"] for e in self.entries), 6)

    @property
    def remaining(self) -> float:
        return round(self.cap_usd - self.total_spent, 6)

    def record(self, project_id: str, provider: str, model: str,
               cost_usd: float, kind: str, *, usage: dict | None = None) -> dict:
        if not math.isfinite(cost_usd) or cost_usd < 0:
            raise ValueError("invalid ledger cost")
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "project_id": project_id,
            "provider": provider,
            "model": model,
            "cost_usd": round(cost_usd, 6),
            "kind": kind,
        }
        if usage is not None:
            entry.update(usage)
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path + ".lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self._reload()
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
