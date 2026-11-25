---
name: debugging
description: Finds and fixes the root cause of a bug, failing test, crash, wrong output, or flaky behavior. Use whenever something does not work as expected, before proposing or writing any fix.
---
# Debugging

No fix without a known cause. A fix for a guessed cause usually hides the bug or moves it somewhere else.

## 1. Get a failing signal

Build one command that shows the bug: it fails now and passes once the bug is fixed. From best to worst:

- an automated test that fails
- a script or CLI command that prints the wrong result
- an HTTP request or a scripted browser step
- a written list of manual steps (last resort; say so in the report)

It must be repeatable, fast, and something you can run yourself. If you cannot reproduce the bug, don't fix it: collect more data (logs, inputs, versions, environment) or ask for it, and report what you tried.

Read the whole error message and stack trace before anything else. They often name the cause.

## 2. Make it small

- Cut input, steps, and code until every remaining part is needed to trigger the bug.
- Look at recent changes: `git log`, `git diff`, and `git bisect` when a known good version exists.
- Compare with a case that works. List every difference between the two.

## 3. Find the cause

- Write down two to five possible causes, each one testable: "If X is the cause, then changing Y makes Z happen."
- Test the most likely one first. Change one thing at a time.
- Trace the bad value back to where it first became wrong. Fix it there, not where it shows up.
- Print what the code actually does instead of trusting what you think it does. Mark every temporary log with one unique tag, such as `DEBUG-7f3a`, so you can find and remove them all later.

## 4. Fix

- For a reported bug, write one regression test that reproduces it and see it fail for the expected reason. When a check you already have is failing on your own unfinished work, that check is the signal; add no test.
- Fix the cause in the shared place every caller goes through. Check every caller of the function you change.
- Make the smallest change that fixes the cause. No unrelated cleanup.
- Run the failing signal (now passing) and the full required checks.

## 5. Clean up

- Remove every temporary log (search for your tag), debug flag, and experiment.
- Revert the attempts that did not help.

## Stop rules

- After three failed fixes, stop guessing: your picture of the problem is wrong. Go back to steps 1 and 2, or question the design, and report what you tried.
- Never make a failure go away by catching and ignoring the error, adding a retry or a sleep without knowing why it fails, loosening an assertion, skipping a test, or returning a fallback value.
- For a flaky test, find what varies: timing, shared state, test order, network, clock, randomness. Wait for a condition, never for a fixed time.
