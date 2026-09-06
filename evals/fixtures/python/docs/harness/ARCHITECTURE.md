# Harness architecture

The Python standard library runner at `scripts/harness.py` owns task transitions, check execution,
evidence freshness, handoff updates, and archival. JSON files under `docs/harness/` are the durable
orchestration state. `scripts/check_harness.py` is an independent plumbing check; it does not
implement CSV parsing or header validation.

The planned product remains outside this fixture's generated scope.
