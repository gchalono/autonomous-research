# V17A offline measurement apparatus

Nothing here changes or executes live research. All bundled sources and ground truth are synthetic developer-authored fixtures, independently specified from the scorer, not independent human annotations. Metrics describe stipulated labels only. No production research quality has been measured.

Entry points: schema.py validates distinct entities and graph integrity; scoring.py returns explicit measurable/undefined metrics or invalid_input/insufficient_adjudication; adapter.py imports the unchanged ExecutionReport contract only to validate/render a supplied payload and leaves inventory uncertified; statistical.py resamples tasks, not claims; cli.py loads frozen JSON and emits deterministic results. CONTRACT_AND_METRICS.md is the scoring/annotation pre-specification. schema_v17a_1.json is generated from the versioned Pydantic schema. No new dependencies (existing Pydantic 2 and pytest for tests).

Frozen ORACLES.json contains hand-specified fractions and rationales for E01–E30. build_corpus.py is an authoring aid, never the oracle scorer. Do not regenerate frozen datasets during a study; a changed manifest invalidates that dataset. Annotators must be blinded, qualified and independent of candidate answers before any real-world quality claims. A certificate cannot mechanically establish that a reviewer found every factual sentence or every semantic paraphrase. False labels/certification require independent review. Exact duplicate texts/proposition keys are rejected; claim atomicity and semantic deduplication still require adjudication. This harness is not an automatic semantic fact checker.

Citation graph validity and full span identity are checked mechanically. Semantic entailment, wrong-source meaning, truth and materiality remain annotation inputs. Replacing evidence requires new judgments and a new frozen dataset version; the scorer must not guess a changed passage's meaning. Production-invalid citations are research defects: represent the claim's missing usable evidence and annotation, rather than creating dangling evaluation graph edges (which invalidate the measurement input).

## Offline replay

Use the project's existing virtual environment; do not install/upgrade dependencies or expose credentials. From a full baseline repository plus these files:

```bash
/path/to/venv/bin/python evaluation_v17a/replay.py full --repository /path/to/repo --output /tmp/v17a-full --protect-repository /path/to/shared-checkout
/path/to/venv/bin/python evaluation_v17a/replay.py harness --repository /path/to/repo --output /tmp/v17a-harness
/path/to/venv/bin/python evaluation_v17a/replay.py characterization --repository /path/to/repo --output /tmp/v17a-characterization
```

The full group adds the V17A acceptance tests to the established offline selection, deselecting only test_live_end_to_end. Characterization is deliberately separate and preserves safe-behavior assertions as strict expected AssertionError failures. Any other exception or an unexpected pass requires investigation. The replay child strips credentials, denies socket/DNS/sendto through the unchanged established audit guard, denies original/snapshot-source and canonical spending writes, retains fresh V6 evidence in a disposable tree and records collection, execution, teardown and session-finalization census. Child CPU/address-space/file-size/time caps apply. This is Python audit isolation for reviewed code, not an OS sandbox against arbitrary hostile native code. No native network clients/subprocesses are used by evaluation tests. It does not disable the inherited cloud controls.

For a self-contained bundle, extract to a temporary directory, verify MANIFEST.sha256 and all MANIFEST.json entries, then substitute `--baseline-directory /extracted/baseline_repository` for `--repository`. The bundle contains the baseline runtime, full existing tests/fixtures, and these evaluation files. Full legacy tests require those baseline packages/audit fixture directories and installed project dependencies; an isolated scorer file is insufficient. The replay runner checks all original snapshot file hashes after testing. The bundle patch is separately checked against an actual disposable git archive of the recorded baseline.

CLI, for already frozen/adjudicated data only:

```bash
python -m evaluation_v17a.cli evaluation_v17a/fixtures/E01.json /tmp/supported.json
python -m evaluation_v17a.cli evaluation_v17a/fixtures/E02.json /tmp/unrelated.json
```

Repeated inputs with identical explicit metadata yield identical JSON; timestamp defaults to null, never an invented execution time. The replay's demonstration saves the exact two CLI inputs/results. Unknown operational values remain null. CLI execution is exercised under the offline guard in the acceptance suite.

Known limits: synthetic-only semantics, attestation-dependent claim completeness and human-label provenance, no independent human labels, no real task dataset, no formal production accuracy claim, no preregistered real-world effect threshold or approved annotation budget. Statistical intervals on synthetic data only test mechanics. Independent Muse audit is required before V17B baseline evaluation authorization.

Engine citation binding: each scored citation names an actual engine source ID cited by its linked engine claim. The frozen source URL and full quote must match that source record. Every explicit engine citation relationship for an inventoried engine claim must be represented; neither evaluation-only citations nor omitted unfavorable citations are allowed. Unlisted summary-only propositions have no inferred engine citation. Narrative-only inline citation conventions require a separately reviewed adapter extension; no semantic link is invented. Independent claims outside the engine registry remain in the inventory and can receive missing-citation labels. Duplicate propositions are one claim ID with multiple exact locations (additional_locations), not multiple scoring units. Known engine claims are either inventoried or explicitly excluded as nonfactual with a reason; excluded text cannot be marked factual. Such exclusions still require independent semantic review. Rendering preserves all original field-string characters, including quotes, Unicode and newlines, in path-tagged lines; render_with_locations maps each field to exact report offsets. No normalization discards source offsets.
