<!-- harness:start (installed by harness-bootstrap; keep project notes outside these markers) -->
## Harness

Run `python3 scripts/harness.py status` before anything else in a session, including after a restart.
Follow [the task workflow](docs/workflow.md). Use `show ID` for acceptance, checks, proof and next steps.
Checks, review paths and delivery settings live in `docs/config.json`; edit tasks through the runner.
Before writing, changing, debugging, testing or reviewing code, read the matching skill in `.agents/skills/`.
Stay within the user's scope. `status` says which delivery steps need approval.
<!-- harness:end -->
