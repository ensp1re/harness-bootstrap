---
name: reviewing-changes
description: Reviews a code change (diff, branch, or pull request) for correct behavior, missed impact, and careless code, and handles review comments on your own change. Use when asked to review a change, when the harness requires a review, before calling your own task done, or when you receive review comments.
---
# Reviewing changes

## Setup

- Read the task first. In the harness: `python3 scripts/harness.py show ID` for acceptance lines and the must-not-change list.
- Get the exact diff against the base: `git diff <base>...HEAD`. Confirm it is not empty.
- Read each changed file around the change, not only the changed lines.
- If the checks have not passed on the current files, run them.

## Pass 1: does it do the task?

- Each acceptance line is met, and a passing check proves it.
- Edge cases: empty, missing, duplicate, very large, concurrent, and outside calls that fail.
- Errors are visible, not swallowed or replaced by fallback values.
- Security and data: input validated at the boundary, no secrets in code or logs, no queries, shell commands, or HTML built from raw input, permissions checked, deletions and migrations safe.
- Nothing outside the task changed, and the must-not-change items are untouched.

## Pass 2: what else does it touch?

- For each changed function, type, field, route, config key, or name, search for uses outside the diff, as `checking-impact` describes. A use that still expects the old shape or behavior is blocking.
- Search for the old names. Leftovers in code, config, docs, or tests are findings.
- Changed input validation with unchanged tests is a risk: check that the tests still prove the behavior.

## Pass 3: is it good code?

Check the project's own rules first (AGENTS.md, linters, nearby code), then the rules in `writing-code` and `structuring-code`. Each finding names the rule it breaks; a personal preference is not a finding.

- Over-engineering first: options, layers, abstractions, or files the task does not need. Could it be clearly shorter?
- Reuse: does it copy something that already exists?
- Structure: new code in the wrong module, wrappers that only pass calls through, `utils` dumping grounds, reaching into another module's internals, import cycles, input and output mixed into core logic.
- A restructure must reduce what a reader has to keep in mind, not just move code around.
- Tests: do they test behavior through the public interface, and fail when it breaks? Invert one condition the change adds; if the tests still pass, they are weak. Watch for expected values computed with the code's own formula, and for heavy mocking. A missing test is a finding only when the workflow requires one.
- Repeated tests: for each test the change adds, name the branch of code it runs. Two new tests on the same branch for the same behavior, at any layer, are **Should fix**: keep the one that shows the acceptance line as written. So is more than one regression test for one bug.
- Careless code: the list in `writing-code`.

Keep the passes separate in the report.

## What to report

- Report a finding only when you are sure it is real. Before reporting it, check it again against the code, or run it.
- Skip problems that existed before the change (one line at most) and anything the linter or formatter already checks.
- Each finding: `file:line`, what is wrong, why it matters, and a concrete fix. Mark its level:
  - **Blocking**: wrong behavior, a security or data problem, a broken use outside the diff, or proof that does not hold. In the harness these are the only reasons for `review ID --fail`.
  - **Should fix**: a structure or clarity problem that will cost time later.
  - **Nit**: a small point; optional. Give a few at most.
- End with one line on what you checked and found fine. Don't approve code you have not read, and don't invent problems to have something to report. If something is unclear, ask instead of guessing.

## When you receive a review

- Check each comment against the code before changing anything. Reviewers can be wrong or miss context.
- Fix blocking findings. Fix the others when they are right and inside the task.
- Push back, with the reason, on suggestions that add features, options, abstractions, or tests the task does not need, or that would break something. "Nothing calls this; remove it instead?" is a valid answer.
- If a comment is unclear, ask before changing code.
- After the fixes, run the checks again and send the change back to the same reviewer.
