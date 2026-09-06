# Generated harness behavioral contract (v1)

This is the shared behavior of native implementations, not a mandate to introduce a framework or a particular source layout. Implement using the selected project's runtime and existing test runner. The JSON protocol below allows the same black-box cases to validate each implementation.

## Invocation and paths

Document a runner command whose arguments follow: `RUNNER --root PATH COMMAND [arguments]`.
Support `context`, `tasks`, `validate`, `verify ID`, `handoff`, `archive ID [--dry-run]`, `deliver ID [--dry-run]`, and `transition ID STATE`. Commands emit one JSON object on stdout; diagnostics/logs go to stderr or referenced files. Use exit 0 for success, 1 for failed checks/blocked transition, 2 for invalid input. Resolve every stored relative path within root; reject absolute paths, traversal and symlink escapes for harness-owned writes. Run with the supplied root, never the caller's directory.

All default paths are relative to the supplied repository root: `docs/harness/config.json`, `docs/harness/tasks.json`, `docs/harness/handoff.json`, `docs/harness/install.json`, `docs/harness/runs/`, and `docs/harness/archive/`. Existing repository paths may override these through the runner's documented configuration discovery. Probe fixtures use the defaults. Reject unsupported schema versions without mutation.

Config v1:
```json
{"schemaVersion":1,"checks":[{"id":"unit","argv":["native-runtime","test-command"],"cwd":".","timeoutSeconds":120,"required":true}],"fingerprintPaths":["src","tests","package.json"],"delivery":{"provider":"github","defaultBranch":"main","requirePR":true}}
```
Check commands are explicit argv arrays executed without shell interpolation. A shell command requires an explicit shell argv entry. Never infer commands from arbitrary task prose. Do not store secrets or dump environment variables; record relevant runtime versions and environment variable names, not values. Missing commands/services fail distinctly from test assertions. Bound execution and kill owned subprocess groups on timeout where supported; document platform limitations.

Tasks v1:
```json
{"schemaVersion":1,"nextId":2,"tasks":[{"id":"F001","behavior":"Observable outcome","acceptance":["Observable acceptance"],"dependsOn":[],"state":"not_started","spec":null,"plan":null,"verification":["unit"],"blockedReason":null,"evidence":null,"delivery":null}]}
```
IDs are `F` followed by at least three digits, unique across live and archived records. nextId is an integer greater than all allocated IDs. Each task has nonempty behavior/acceptance, valid dependency/check references and optional existing relative spec/plan paths. Reject cycles and duplicate IDs. At most one active task. An archived satisfied dependency remains satisfied. Empty queue is valid; empty verification cannot establish product success.

## State and command behavior

- `context`: read-only output with `schemaVersion`, actual git branch/revision/dirty status when available, active task, ready task IDs, blockers, evidence freshness and next action. Never invent git facts for a non-git root.
- `tasks`: read-only list including deterministic ready IDs: not_started tasks whose dependencies are passing. Tie-break by numeric ID.
- `validate`: check schema, types, IDs, references, dependencies, state/evidence consistency, configured plan/handoff references and required docs links. Return `{"ok":boolean,"errors":[...]}`. Malformed JSON produces a clean diagnostic, not a stack trace.
- `transition`: legal edges are not_started->active, active->blocked, blocked->active, active->verified (only verify command), verified->active, verified->passing (deliver command only). Blocked requires a reason supplied via `--reason TEXT`. Activation requires satisfied dependencies and the WIP limit. No direct arbitrary state assignment.
- `verify ID`: only active tasks. Run all referenced checks and always retain outcomes. Mark verified only when all required checks pass and acceptance has appropriate evidence. Each criterion must map to a check or a separately recorded manual/runtime review; unknown manual results block. Non-applicability must be explicit in the task with rationale and must not silently override a globally required check. Missing checks, empty recipes, timeouts and interruptions never pass.
- `handoff`: refresh objective git/task/evidence fields atomically, preserving `decisions`, `rejectedApproaches`, `blockers`, and `nextAction` authored by the user/agent. Validate referenced task/plan IDs; do not convert queued work into active work. Return the resulting checkpoint. Generate the readable handoff from this source rather than maintaining duplicate objective facts.
- `archive ID [--dry-run]`: require one explicit passing task ID; never default to all tasks. Move that passing entry into durable per-task records before removing from live queue. Keep IDs and dependency resolution. Do not prune by wall-clock age in CI. On error leave recoverable original state, never silently discard evidence. Dry-run is read-only.

Plan metadata should identify its current task; validate that it matches the queue or is explicitly queued/paused. A plan may exist without an active task. Distinguish next scheduled step from work actively running. Link checks must not require arbitrary heading wording.

## Evidence and freshness

Each attempt has a stable ID and a started record written before commands. Store status (running/passed/failed/interrupted), timestamps, check IDs, argv/cwd, exit/timeout classifications, runtime facts and full log paths. Record compact summaries separately from logs. Recovery treats unfinished attempts as interrupted, never successful. Atomic replace plus a single-writer lock protects state; concurrent mutation fails clearly. Reconcile stale locks by verifying owner liveness rather than deleting on age alone.

Fingerprint required input paths recursively, including file names/content, added/deleted files, relevant manifests/lockfiles, check configuration, acceptance/spec/plan inputs. Exclude generated evidence and state-output fields to avoid self-invalidating hashes. Do not exclude user-authored requirements embedded in state. Missing configured inputs must fail or be explicitly optional. Capture fingerprints before and after verification; mutation during checks invalidates the run. Generated build/cache paths must be outside the input set or explicitly excluded.

`context` and `validate` recompute freshness. `validate` returns nonzero for stale or unavailable evidence on verified/passing tasks; do not downgrade it to a successful warning. A stale verified task remains historically verified but cannot pass delivery; report `fresh:false` and require reactivation/reverification. Logs should be local/gitignored by default, with durable sanitized summaries committed and CI artifacts linked according to repository policy. No evidence storage is tamper-proof inside an agent-writable repository.

## GitHub delivery

This first version targets GitHub. Generate project-native delivery integration using git and gh (or an existing GitHub integration with equivalent verified outputs). Do not generate fictitious CI links when no workflow exists. Missing GitHub setup is explicitly unavailable. Discover protected/default branch; never push directly to it. Preserve existing hooks and CI. Full local gate precedes normal push; draft PR and required successful CI must refer to the implementation revision. Validate actual remote/PR/check results rather than accepting a user-written URL as proof. Missing host/auth leaves delivery blocked, not passing.

Record implementation revision separately from the state-only closeout revision. The closeout may update only harness bookkeeping; it goes through normal hooks and CI. Do not recursively demand another completion commit for that commit. Any product/check/spec change during closeout requires a new implementation verification. Never bypass hooks, auto-merge, deploy, weaken required checks or change repository protection settings.

## Native tests required

Test malformed inputs; legal/illegal transitions; duplicate IDs; cycles; unsatisfied dependencies; one active task; no checks; missing executable; failing/timeout/interrupted checks; post-verification source/requirement/config changes; changes during verification; preserved handoff prose; interrupted writes; archived dependencies; rerun preservation; missing git/remote/auth; CI failure and successful implementation plus bookkeeping closeout. Fixtures must simulate external delivery, never publish for a test.

## Readiness report

At bootstrap exit, emit a readiness report with separate `harnessValidation`, `productBaseline`, and `deliveryReadiness` statuses. Each is `passed`, `failed`, or `unavailable` with observed evidence and remaining actions. A passed probe is only smoke coverage. Include a contract-coverage table for implemented/tested, implemented/untested, and unavailable capabilities. Do not call initialization complete while generated core state, evidence or recovery tooling lacks required behavior; finish it or report the exact blocker. Product behavior and remote delivery may remain queued/blocked independently.

For fixture evaluation, stub external GitHub responses with recorded inputs/outputs; never create remote state. Persist only metadata needed for replay/reconciliation, not opaque model reasoning. No mandatory scheduler, runtime hook or full conversation capture is required.

## Exact delivery interface

`deliver ID --dry-run` is read-only: report local evidence freshness, Git branch/revision/dirty state, remote/PR identity if accessible, missing checks and proposed actions. `deliver ID` performs the configured GitHub delivery only within existing explicit user authorization for push and PR creation. The bootstrap request itself is not authorization to deliver future product tasks. Never ask again when the current request already authorizes delivery.

The command requires a committed, locally verified implementation revision on a feature branch. It pushes normally, finds or creates its draft PR, waits for configured required CI checks with bounded timeout, verifies they apply to that revision, and records delivery evidence before the verified->passing transition. On missing authorization/configuration/auth, push failure, failed/pending/timed-out CI or changed inputs, preserve verified/active state and report the blocker. Commit preparation follows project policy; never auto-stage unrelated changes. State-only closeout is described above; resume by inspecting the remote before repeating writes.

## Minimal auxiliary records (v1)

These keys are required; implementations may add namespaced metadata. Relative paths use the repository root.

- Handoff: `schemaVersion`, `taskId` (string/null), `plan` (path/null), `git` (actual branch/revision/dirty, or null), `evidenceRefs` (array), `decisions` (array of strings), `rejectedApproaches` (array), `blockers` (array), `nextAction` (string), `updatedAt` (UTC timestamp). Refresh objective fields and preserve narrative fields.
- Install: `schemaVersion`, `skillVersion`, `runtime`, `files` (array of `{path, sha256}` covering generated content), `updatedAt`. Hash recorded content after successful writes; an existing differing hash requires reconciliation.
- Attempt: `schemaVersion`, `id`, `taskId`, `status`, `startedAt`, `endedAt` (timestamp/null), `fingerprintBefore`, `fingerprintAfter` (string/null), `checks` (array of `{id, argv, cwd, status, exitCode, logPath}`), `runtime` (version facts), `errors` (array). Failed attempts remain retained.
- Archive: `schemaVersion`, `task` (complete passing task record), `archivedAt`. Store at `docs/harness/archive/ID.json`; never overwrite a different archived record.
- Delivery: `implementationRevision`, `remote`, `prUrl`, `checkRuns` (names, revision, conclusion, URL), `observedAt`, optional `closeoutRevision`. Validate with host observations, not user-authored JSON.

## Fingerprint input projection

Hash sorted relative file names and SHA-256 content digests for configured paths. Recurse directories so additions/deletions affect identity. Hash the full verification config and the task's `id`, `behavior`, `acceptance`, `spec`, `plan`, `verification`, plus any acceptance-to-check mapping or applicability rationale; referenced spec/plan files are included. Exclude `state`, `evidence`, `delivery`, timestamps, lockfiles and generated run/handoff/install/archive outputs from the task-state projection. Product dependency lockfiles are inputs and must not be confused with harness process locks.

Serialize projections as UTF-8 JSON with lexicographically sorted object keys, no insignificant whitespace, arrays in original order, and no floating-point fields. Hash raw file bytes; explicitly document line-ending effects. Do not silently omit unreadable inputs. A timestamp alone is not evidence identity.
