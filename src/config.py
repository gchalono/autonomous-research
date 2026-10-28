"""Configuration for the autonomous research system.

All settings come from the environment (never from code defaults baked into
agent prompts), so spending limits, model choices and revision caps are
ordinary software configuration -- not LLM decisions. See README for the
full list of variables.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def load_dotenv(path: str | None = None) -> str | None:
    """Load a local ``.env`` file into the environment (no overwrites).

    Returns the path loaded, or None if no file exists. Only the first
    ``KEY=VALUE`` form is supported (optional ``export`` prefix, optional
    single/double quotes). Values are never printed or logged by this
    function. This is the supported local configuration mechanism alongside
    real environment variables; the application never reads keys from any
    other file.
    """
    import pathlib

    if path is None:
        here = pathlib.Path(__file__).resolve().parent.parent
        path = str(here / ".env")
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        return None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
    return path


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    """Runtime settings. ``from_env`` is the only supported constructor."""

    # Where projects live (SQLite DB + per-project artifact dirs).
    projects_root: str = "projects"
    # Per-project spending target in USD. A target, not a hard guarantee:
    # the orchestrator stops before any call that would push estimated spend
    # past it, and external tool costs are tracked separately.
    budget_usd: float = 10.0
    # Revision / correction caps enforced by the orchestrator, never by LLMs.
    max_prompt_revisions: int = 3
    max_corrections: int = 2
    max_tool_iterations: int = 12
    max_sources_to_verify: int = 8
    llm_timeout_s: int = 120
    tool_timeout_s: int = 30
    # Preflight budget estimation: assumed output tokens per LLM call when
    # checking a call against the remaining budget before it is made.
    # A guardrail heuristic, not a billing prediction.
    estimated_output_tokens: int = 1500
    # Maximum wall-clock runtime per project in seconds (default 1 hour).
    # The engine fails the run (with artifacts preserved) when exceeded.
    max_runtime_s: int = 3600
    # Explicitly configured fallback model, used ONLY when the provider
    # reports the configured model unavailable. Never silently substituted
    # otherwise, and always recorded in run metadata.
    model_fallback: str | None = None
    # Cost recorded per web_search call when set (> 0). Tavily bills per
    # search; the default 0 means "unknown -- count calls, bill nothing",
    # because inventing a search price would corrupt cost accounting.
    tavily_cost_per_search: float = 0.0
    # Cumulative validation budget across ALL projects (Phase 4
    # authorization: $30 total). The ledger persists this cap's spend so
    # failures, restarts, and resumes can never reset it.
    total_validation_budget_usd: float = 30.0
    # Model per agent role. Names are configuration, not hard-coded logic.
    # Defaults verified against OpenAI's model list during the Phase 2
    # audit (Oct 2026): gpt-5 / gpt-5-mini / gpt-5-nano are DEPRECATED with
    # shutdown announced for Dec 11, 2026. Re-verify model ids before any
    # production run -- model availability changes, and these defaults will
    # rot again. Override with AR_MODEL_* env vars.
    models: dict = field(default_factory=lambda: {
        "creator": "gpt-5.4-mini",
        "evaluator": "gpt-5.4-mini",
        "executor": "gpt-5.6-terra",
        "auditor": "gpt-5.6-terra",
    })
    # Approximate USD price per 1M tokens (input, output). Used only for
    # budget estimation; real bills come from the provider. Current-default
    # prices re-verified Oct 28, 2026 against third-party compilations of
    # OpenAI's pricing page (multiple sources agree): gpt-5.4-mini
    # $0.75/$4.50, gpt-5.6-terra $2.00/$12.00. Re-verify against OpenAI's
    # pricing page before relying on budget math -- prices change, and
    # long-context (>272K input tokens) rates run ~2x input / 1.5x output.
    model_prices: dict = field(default_factory=lambda: {
        "gpt-5.4-mini": (0.75, 4.50),
        "gpt-5.6-terra": (2.00, 12.00),
        "gpt-5": (1.25, 10.00),
        "gpt-5-mini": (0.25, 2.00),
        "gpt-5-nano": (0.05, 0.40),
    })
    # Arbitrary generated-code execution is OFF by default. A Python
    # subprocess is not a sandbox; enabling it requires an explicit opt-in
    # and it still runs with timeouts and no network (see tools/computation).
    allow_code_execution: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        models = {
            "creator": os.environ.get("AR_MODEL_CREATOR", "gpt-5.4-mini"),
            "evaluator": os.environ.get("AR_MODEL_EVALUATOR", "gpt-5.4-mini"),
            "executor": os.environ.get("AR_MODEL_EXECUTOR", "gpt-5.6-terra"),
            "auditor": os.environ.get("AR_MODEL_AUDITOR", "gpt-5.6-terra"),
        }
        return cls(
            projects_root=os.environ.get("AR_PROJECTS_ROOT", "projects"),
            budget_usd=_env_float("AR_BUDGET_USD", 10.0),
            max_prompt_revisions=_env_int("AR_MAX_PROMPT_REVISIONS", 3),
            max_corrections=_env_int("AR_MAX_CORRECTIONS", 2),
            max_tool_iterations=_env_int("AR_MAX_TOOL_ITERATIONS", 12),
            max_sources_to_verify=_env_int("AR_MAX_SOURCES_TO_VERIFY", 8),
            llm_timeout_s=_env_int("AR_LLM_TIMEOUT_S", 120),
            tool_timeout_s=_env_int("AR_TOOL_TIMEOUT_S", 30),
            estimated_output_tokens=_env_int("AR_ESTIMATED_OUTPUT_TOKENS", 1500),
            max_runtime_s=_env_int("AR_MAX_RUNTIME_S", 3600),
            model_fallback=os.environ.get("AR_MODEL_FALLBACK") or None,
            tavily_cost_per_search=_env_float("AR_TAVILY_COST_PER_SEARCH", 0.0),
            total_validation_budget_usd=_env_float("AR_TOTAL_VALIDATION_BUDGET", 30.0),
            models=models,
            allow_code_execution=os.environ.get("AR_ALLOW_CODE_EXECUTION", "") == "1",
        )

    def estimate_cost_usd(self, model: str, input_tokens: int, output_tokens: int) -> float:
        in_price, out_price = self.model_prices.get(model, (1.0, 5.0))
        return (input_tokens * in_price + output_tokens * out_price) / 1_000_000.0
