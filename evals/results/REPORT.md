# Evaluation record — 2026-09-06

This release is a bootstrap skill with a normative generation contract, not a prebuilt cross-stack runtime. Independent Luna/max agents generated Node and Python fixtures; the parent ran and strengthened executable probes. The initial evaluation was interrupted by an account usage limit, then resumed locally. No comparative quality/cost claim is established.

## Observed results

- Official skill-creator validation: passed with PyYAML 6.0.3 in a temporary dependency directory.
- Template manifest and local link checks: 9 templates passed.
- Probe's own tests: 2 passed (reject an always-success fake runner; restore fixture after runner failure).
- Node fixture: 6 basic probes and 8 scenario probes passed after repairs.
- Python fixture: 6 basic probes and 8 scenario probes passed after repairs.
- Scenario results are stored alongside this record. Fixtures are reproducible snapshots under ../fixtures, not maintained generation templates.

## Findings and repairs

1. Templates originally disagreed with the contract's task states. Aligned states and made handoff a view of its JSON checkpoint.
2. Python generation allowed a merely verified dependency to unblock a task. Corrected readiness/activation to require passing dependencies.
3. Node generation reported stale evidence as a successful warning and did not bind requirements/check config to evidence. Corrected validation and fingerprint inputs; reran verification and all scenario probes.
4. The Node evaluation created sample product code to exercise verification. The skill now explicitly prohibits implementing product features during bootstrap merely to make checks pass. The saved code is only a synthetic evaluation input, not evidence of compliant bootstrap scope.
5. Basic probes missed important failures. Added scenario_probe.py, and required both smoke and scenario protocols before readiness claims.

## Limits

These are bounded fixture evaluations, not full conformance certification. End-to-end GitHub delivery, independently trusted CI identity, multi-process crash/lock recovery, repeated initialization across every conflict type, comprehensive path/symlink boundaries and fresh-agent continuation across multiple sessions remain unverified. The fixtures contain incomplete integrations (including simplified/local delivery); their passed probes do not waive the contract for a generated user repository.

The planned repeated baseline-versus-harness trials, held-out agent tasks, and token/cost comparisons were not run. Their protocol is provided in ../README.md. The skill requires actual capability reports per generated project and must not describe an incomplete native runner as ready.

## Final review corrections

A separate read-only review identified undefined delivery syntax, ambiguous auxiliary schemas/fingerprint inputs, missing lifecycle command routing, and optional-document link handling. The contract now defines deliver/archive forms, full default paths, minimal record schemas, and fingerprint projection. Templates route through the harness runner and retain existing user authorization boundaries. These documentation changes were structurally checked; the earlier native fixtures predate the expanded schema and are not certified implementations of it.

Go 1.27.1 fixture: native `go test ./...` passed and all six basic probes passed. Source-change freshness, failed-check evidence, dependency cycles and preserved handoff are covered by native tests. See go-report.md for detailed limits.
