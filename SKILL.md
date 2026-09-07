---
name: harness-bootstrap
description: Create or reconcile a repository-local development harness from a project description, including specifications, work tracking, session handoff, native verification tooling, and GitHub delivery checks. Use for requests to bootstrap or improve the project harness, not ordinary feature implementation.
---
# Harness Bootstrap

Turn a product description into a repository that a fresh coding-agent session can understand, verify, and resume. Bootstrap ends with the harness validated and product work queued, unless the user also authorizes implementation.

## Discover and agree

Inspect repository instructions, git status, manifests/lockfiles, runtime versions, existing docs, test commands and CI before asking for facts. Preserve existing work and conventions. Do not implement a sample product merely to make bootstrap checks green. Keep test-only plumbing fixtures isolated from the target product. For an empty repository, establish product outcomes, non-goals, stack, and acceptance criteria with the user. Ask only questions whose answers change the result; do not invent product choices or verification success.

Default to the project's native runtime, generating the tooling anew against [the behavioral contract](references/contract.md). Do not require Node for Python/Go projects or Python for Node projects. If no runtime is chosen, resolve that before generating executables. Reuse verified commands from project configuration; treat file names as clues, not proof.

This first version integrates GitHub delivery; other hosts are reported as unsupported rather than given fictitious workflows. Default delivery is a feature branch, full local gate, pushed implementation, draft GitHub PR, successful CI, and verified state-only closeout. Missing remote/access is a delivery blocker, not a reason to fabricate evidence or block useful local preparation. Pushes/PRs remain subject to the user's actual authorization; never infer deployment or merge permission.

## Generate and reconcile

Read [the contract](references/contract.md) and use [the template map](assets/templates/README.md) as adaptable source material. Put generated documents and state/config files directly in `docs/`, and native tooling directly in `scripts/`. Do not create a harness subdirectory in either location. Preserve existing canonical files and reconcile naming conflicts without overwriting user content.

Generate a compact AGENTS router, product/architecture facts, live queue, current handoff, reliability/security instructions and initial bounded plan. Create change records only for substantial behavior changes. Small tasks need a queue entry, not a document ceremony. Include only non-obvious rules and useful routing; omit speculative background and duplicate instructions.

Expose the command interface in the contract using native tooling and the repository's command conventions. It must work without this skill installed. Do not create mandatory `.agents` or `.claude` trees. Derive objective facts mechanically; keep decisions and next actions human-readable.

Inventory proposed files before writing. Preserve existing instructions, CI jobs and user edits. Record generated files and content hashes in the install manifest. On rerun, replace only unchanged generated content; reconcile edited files surgically and report conflicts. Never delete unrelated files. Use schema versions and explicit migrations; don't reset live state on upgrades.

Native generation is not permission to improvise away contract requirements. If a capability cannot be implemented and tested, report it as unavailable and leave readiness incomplete.

## Verify

Use [evaluation scenarios](evals/README.md). Run `scripts/check_bundle.py` when changing bundled assets. Run the generated runner's native tests and both probe protocols (basic state checks plus scenario checks on an explicitly verified fixture). A basic probe alone cannot establish freshness or dependency correctness. The bundled `scripts/probe.py` is an authoring/evaluation helper only: it is not a dependency of generated projects. If Python is absent, implement the same probes in the available runtime.

Run real available baseline checks. Empty projects may pass harness validation while product readiness remains unverified; queue setup of missing product checks. Do not install or start unrelated infrastructure solely for template validation.

For substantial skill changes, use a fresh evaluator with a realistic request and raw fixtures, withholding expected output. Compare against a compact baseline. Evaluate requirements, edits preserved, stale evidence, false completion, interruption and fresh-session resumption. Record failures and observed results; never invent token/cost measurements.

Research or review subagents are optional when independent work helps. One coordinator owns queue/handoff changes. Give bounded context and responsibility, respect configured model choices, and use no parallel implementation without explicit authorization.

## Closeout

Report what was generated, native checks executed, remaining setup/delivery blockers, and the first queued product task. Leave current state consistent. Do not claim the product is built, publish anything automatically, or turn a successful bootstrap into indefinite execution.

See [research rationale](references/research.md) when evaluating a new mechanism. Retain or remove process based on observed behavior, rather than adding rules after every isolated failure.
