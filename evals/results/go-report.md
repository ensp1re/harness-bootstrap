# Go forward evaluation

Date: 2026-09-06
Runtime: Go 1.27.1 (darwin/arm64)
Fixture: `evals/fixtures/go`

## Result

The bounded native Go fixture builds and passes its focused tests. It does not add or implement a
product service.

Commands executed:

```text
go test ./...
go build -o harness-runner ./cmd/harness
python3 ../../../scripts/probe.py --root fixture -- ./harness-runner
```

Observed results:

- `go test ./...`: passed. Native tests cover malformed JSON, duplicate IDs, dependency cycles,
  legal activation, illegal direct verification, passing verification, failed checks with retained
  evidence, dependency activation, source fingerprint freshness invalidation, and handoff prose
  preservation.
- Contract probe: passed all 6 cases: context, valid state, malformed state, duplicate ID,
  missing dependency, and invalid activation.
- The fixture's `validate` and `context` commands both return valid JSON with exit 0 on clean state.

## Coverage table

| Contract area | Status | Evidence |
| --- | --- | --- |
| JSON protocol and exit classes | implemented/tested | `harness/harness.go`, native tests, probe |
| Schema/ID/dependency validation | implemented/tested | native tests and probe |
| Legal/illegal task transitions and one active task | implemented/tested | native tests |
| Native argv check execution | implemented/tested | passing and failing `/bin/sh` checks |
| Failed check evidence retention | implemented/tested | `TestTransitionsFailedChecksFreshnessAndHandoff` |
| Fingerprint freshness invalidation | implemented/tested | source edit followed by `context` |
| Handoff objective refresh with preserved prose | implemented/tested | native test |
| Atomic state writes | implemented, untested | temp-file + rename path exists |
| Timeout/interrupt process recovery | implemented, untested | timeout flag exists; no bounded test in this fixture |
| Archived dependency resolution | implemented, untested | archive path and ready check exist |
| Git facts | implemented, untested | best-effort local `git` commands |
| Delivery/CI/GitHub integration | unavailable | intentionally omitted from this fixture |
| Product acceptance and remote delivery | unavailable | no product implementation or external publishing |

This is a smoke/forward evaluation fixture, not a production-complete harness. It does not claim
coverage for subprocess group killing, concurrent lock recovery, full plan/spec reference rules,
GitHub auth/CI reconciliation, or comparative multi-trial agent outcomes.
