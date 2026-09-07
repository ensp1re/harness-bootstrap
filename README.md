# harness-bootstrap

`harness-bootstrap` is a reusable Codex skill for turning a plain project description into a
repository-local development harness. It creates the project facts, live work queue, native
verification interface, session handoff, reliability and security rules, and delivery readiness
records that a fresh coding-agent session can use without access to the original conversation.

The skill is Codex-first and generates tooling in the repository's native runtime. It does not
install a universal Node or Python runner, create product code to make checks pass, or require
`.agents` or `.claude` directories. Bootstrap stops with product work queued unless the user also
authorizes implementation.

## Use it

Install this directory as `harness-bootstrap` under your Codex skills directory, or install the
repository with the Codex skill installer. Then invoke it with:

```text
$harness-bootstrap
Bootstrap a harness for [your project description]. Preserve [existing constraints] and queue the first product task.
```

Generated documents and state files live directly in `docs/`, native tooling in `scripts/`, and
tests in `tests/`. None of these locations gets an extra harness subdirectory.
The generated repository owns its runner and remains usable when this skill is not installed.
The normative command, state, evidence, freshness, handoff, and GitHub delivery contract is in
[`references/contract.md`](references/contract.md). The template map is in
[`assets/templates/README.md`](assets/templates/README.md).

## What is included

- adaptable templates for project facts, architecture, plans, changes, handoff, reliability,
  security, technical debt, and repository instructions;
- a native-runtime generation contract with JSON command output and explicit task transitions;
- bundle/link validation, black-box probing, and scenario probing helpers;
- independent Node, Python, and Go evaluation snapshots with recorded limitations;
- research notes explaining the design choices and the methods that were considered.

The evaluation fixtures are raw snapshots, not production runner templates. Their `AGENTS.md`
files and project instructions are test data and must not be treated as instructions for this
skill repository. The reports deliberately separate harness validation, product baseline, and
GitHub delivery readiness; passing fixture probes do not certify a generated project or remote CI.

## Validate the bundle

From the repository root:

```sh
python3 scripts/check_bundle.py
python3 -m unittest discover -s evals -p 'test_*.py'
```

The broader evaluation protocol is documented in [`evals/README.md`](evals/README.md), and the
current bounded results are in [`evals/results/REPORT.md`](evals/results/REPORT.md).
