# Existing project instructions

- Preserve this file and its directives during harness bootstrap.
- The product is a Python CLI that will eventually check CSV headers.
- Do not claim the product is implemented until an independent product check passes.

## Harness router

The current state is in [`docs/tasks.json`](docs/tasks.json). Read the active task's
plan and [`docs/SESSION_HANDOFF.md`](docs/SESSION_HANDOFF.md) before resuming.
The native runner is `python3 scripts/harness.py --root .`; use `context`, `tasks`, `validate`,
`transition`, `verify`, and `handoff` as the lifecycle commands. F001 remains queued until an
independent product check passes. The plumbing check for F002 is evidence about the harness only.
