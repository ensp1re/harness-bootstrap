---
name: simplifying-code
description: Makes recently changed code simpler and clearer without changing what it does, working on the current diff unless a wider scope is named. Use after a feature or fix works and before review, or when asked to clean up, simplify, or refactor code.
---
# Simplifying code

Goal: the same behavior, less to read.

## Rules

- Behavior stays exactly the same: every input, output, side effect, error, and log that callers rely on.
- Scope is the current change (`git diff <base>...HEAD` plus uncommitted edits) unless the user names a wider one. Don't touch unrelated code.
- The checks pass before you start and after each step. Code with no test covering it stays as it is, unless the task allows adding a test first.
- Before removing something that looks odd, find out why it exists: `git log -L` or `git blame`, and search its callers. If you cannot tell, leave it and mention it.
- One simplification at a time; run the checks after each.
- A cleanup goes in its own commit, separate from behavior changes.

## What to look for, most valuable first

1. Code that repeats something already in the repo or the standard library: use the existing one.
2. Code nothing calls, options nobody passes, branches that cannot run: delete them.
3. Wrappers and layers that only pass calls through: inline them.
4. Deep nesting: return early for edge cases.
5. Long if/else chains on one value: a lookup table or a match/switch.
6. Nested ternaries: plain if/else.
7. A boolean parameter that switches behavior: two functions.
8. A variable that only renames another: inline it. A hard-to-read expression: give it a named variable.
9. Error handling that catches and ignores, or checks cases that cannot happen: remove it.
10. A comment that repeats the code: delete it. Code that needs a comment to be understood: rename or restructure instead.
11. A vague name: rename it to the domain term.

## Don't

- Don't compress code into clever one-liners. Shorter is not the goal; easier to read is.
- Don't merge functions that do different jobs just to have fewer of them.
- Don't remove an abstraction that has several real users or hides a decision that may change.
- Don't change public names, formats, or error messages that callers rely on.
- Don't reformat files; that is the formatter's job.

## Finish

- List what you simplified in a few lines, and what you saw but left alone, with the reason.
- Run the checks again.
