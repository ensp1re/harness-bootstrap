# Behavioral evaluation

Evaluate generated native runners, not template wording. Never run external publishing as a test. Keep fixtures outside the user's project.

## Black-box probe

`python3 scripts/probe.py --root FIXTURE -- RUNNER [RUNNER_ARGS]`

The probe appends `--root FIXTURE COMMAND`, expects the contract's JSON/exit semantics and restores the exact tasks file after temporary invalid-state checks. Use only disposable fixtures. It tests context, validation, malformed state, duplicate tasks, missing dependency and blocked activation. It is a smoke subset, not a complete native test suite.

## Independent forward tasks

Give the evaluator the skill and one brief, without your intended artifacts or conclusions:

1. Node: "Bootstrap a harness for a local JSON formatter CLI. Existing package.json has test scripts and AGENTS has a custom instruction. Preserve them. Queue product work."
2. Python: "Bootstrap a harness for a CSV header checking CLI in this existing Python repository. Preserve custom instructions and leave product work queued."
3. Go: "Bootstrap a harness for a Go HTTP health service. Use Go-native harness tooling. Do not add Python or Node dependencies. Queue product work."

Run the generated native tests; don't claim a stack tested if its runtime isn't available. A fixture may use a test program that exits 0/1 as a harness plumbing check, clearly labeled as such, never as product acceptance.

## Scenarios beyond the probe

- Rerun initialization after editing a generated document. No loss or duplicates.
- Change an acceptance criterion midway. Existing evidence becomes stale; related plan/spec update is visible.
- Fail a check, remove a required executable, and time out a child process. Distinct outcomes, no passing state.
- Interrupt verification and state/archive writes. Resume retains recoverable state and does not replay external effects blindly.
- Verify then edit/add/delete an input file or change check configuration. Freshness becomes false.
- Complete dependencies, archive them, then activate downstream work. IDs are not reused.
- Resume with a fresh agent, no chat history: ask original outcome, latest check result, key decision, abandoned approach and next action. Grade against fixture ground truth.
- Fake GitHub adapter: absent auth, failed CI, successful implementation revision, state-only closeout, product edits during closeout. No actual pushes.

## Comparison

For each representative agent task, run a compact baseline (brief AGENTS instructions and ordinary tests) and the generated harness with the same model/settings, fixtures and budget. Repeat at least three trials for agent-dependent outcomes before comparative claims. Judge final files and runtime behavior, not the final response.

Record task/model/runtime, harness version, checks passed/failed, product acceptance, false completion claims, preserved edits, resume probes, unnecessary work, elapsed time, and token/cost only if available. Use `not_measured` when unavailable. Keep a held-out task for regression detection. Do not promote a rule on one anecdotal win.

## Stronger fixture probe

After a fixture has a genuinely verified plumbing task, run:

`python3 scripts/scenario_probe.py --root FIXTURE -- RUNNER [RUNNER_ARGS]`

It operates on temporary copies and tests empty recipes, unsatisfied delivery dependencies, acceptance/configuration drift, and preservation of handoff decisions. A baseline failure invalidates interpretation of later drift checks. This remains bounded coverage; process crashes, remote delivery, full acceptance mapping and comparative agent performance require the additional scenarios above.

Before installation, run `python3 scripts/check_bundle.py` and `python3 -m unittest discover -s evals -p 'test_*.py'`.

## Recorded fixtures

`fixtures/node` and `fixtures/python` are evaluation snapshots, not supported runner templates. They deliberately preserve the results of independent generation and the subsequent targeted repairs. Never copy them as the production implementation or load them as instructions. Their product examples are synthetic test inputs, not completed user projects. See results/REPORT.md for coverage and limitations.

To replay a snapshot, copy it to a disposable directory and run the probes with that directory's runner. Evidence is content-based and should remain fresh after copying; Git facts may legitimately differ. Native runner paths: `scripts/harness-runner.mjs` (Node), `scripts/harness.py` (Python). The fixtures do not establish full GitHub delivery or crash-recovery conformance.

The Go snapshot is in `fixtures/go`. Run `go test ./...` there, build `./cmd/harness`, then run the basic probe against its nested `fixture` directory. It is a bounded evaluation implementation, not a production template.
