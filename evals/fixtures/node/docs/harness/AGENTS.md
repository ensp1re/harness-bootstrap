# Harness router

Read the repository root AGENTS.md first. Harness state lives in this directory.

- Run `node scripts/harness-runner.mjs --root . context` for current state.
- Run `node scripts/harness-runner.mjs --root . tasks` for ready work.
- Run `node scripts/harness-runner.mjs --root . validate` before relying on evidence.
- Product implementation is queued in tasks.json; harness bootstrap does not implement it.
