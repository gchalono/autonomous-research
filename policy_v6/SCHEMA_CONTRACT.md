# V6 contract defined before implementation

The old loader had no policy version, only USD/review-text/expiry checks plus deferred per-request parsing. It accepted unknown keys. SQLite ledger schema 2 is unrelated and will remain unchanged.

Implement explicit policy schema version **1**, retaining current provider field names and canonical paths. Required root metadata: policy_schema_version, state (draft/reviewed), experiment_id (existing fixed experiment), currency USD, monetary_precision 6, budget_micro_usd (integer 1..1,000,000), max_individual_reservation_micro_usd, max_aggregate_reserved_micro_usd, max_concurrent_requests (only 1), max_sdk_retries (only 0), evidence, expires_at, pricing_references, openai map, tavily object-or-null. Limits must satisfy individual <= aggregate <= budget <= $1. Unknown root/nested keys and all unsupported constraint fields are rejected.

Reviewed policies require every enabled provider/model to have complete positive bounds, decimal-string/integer prices (no floating-point price literals), verified review-status declarations and provider-appropriate references. Declared model allowlists are exact dictionary keys; supported endpoints remain compiled into adapters, not arbitrary policy URLs. Operator declarations/references do not prove price truth; official source review is still external.

OpenAI required per-model keys: max_input_tokens, max_output_tokens, max_request_bytes, input_token_overhead, input_bound_mode, input_usd_per_million, output_usd_per_million, pricing_status. Provider-context mode additionally requires matching provider_context_tokens and context_evidence; those fields are prohibited in text-only mode. Input allowance must exceed overhead. Forecast maximum must fit the individual reservation cap.

Tavily required keys: basic_search_max_usd, usd_per_credit, max_credits_per_search, pricing_status. The declared maximum must cover units times unit price and fit the individual cap. Actual credits exceeding the declared unit maximum must freeze continuation.

Draft policies may contain null unresolved bounds/prices and unverified statuses. They can be structurally inspected but cannot construct a usable SpendingGuard, initialize an allowance or dispatch. Reviewed policies must be unexpired with nonempty review evidence. Loading never initializes a ledger. No automatic legacy migration or activation is introduced.

The existing reservation mechanism will enforce the new per-policy individual/aggregate/budget ceilings inside its existing SQLite transaction and validate effective policy before initialization and dispatch transitions. Legacy unversioned formats require explicit reviewed migration; none will be silently upgraded. Existing fixtures will be migrated explicitly as synthetic reviewed attestations, preserving prices and assertions; incomplete fixtures will now expect earlier rejection.
