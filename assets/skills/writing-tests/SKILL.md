---
name: writing-tests
description: Writes tests that catch real bugs and survive refactoring; whether a test is needed at all follows the project workflow. Use when adding or changing a test, reproducing a bug with a test, or judging whether existing tests are good.
---
# Writing tests

The project workflow (`docs/workflow.md`) decides when a test is needed. This skill covers how to write one.

## What to test

- Behavior through the public interface: what a caller or user can observe. Not private functions, internal calls, or the order of internal steps.
- A good test fails when the behavior breaks and keeps passing through any refactor that keeps the behavior. A test that breaks on a refactor tests the implementation.
- How many: one test per acceptance line or reported bug. Add a boundary case (empty, zero, maximum, invalid input) only when the acceptance line or the bug is about it. Don't test every combination of inputs.
- Before adding a test, look for an existing one that covers the same behavior. Change or extend it instead of adding a near copy.
- Not the language, the framework, constants, copied text, or layout.

## How to write one

- Red first: run the new test before the fix or feature exists and see it fail for the expected reason. A test you never saw fail proves nothing.
- One behavior per test. The name states the behavior and the expected result: "rejects an expired coupon", not "coupon test 2".
- Keep the setup short and inside the test, so a reader understands it without opening several helper files.
- The expected value comes from an independent source: a number worked out by hand, an example from the spec, a known fixture. Never compute it with the same formula the code uses.
- Assert the exact result that matters, not just "not empty" or "was called".
- Prefer plain, slightly repeated tests over clever shared test helpers.

## Fakes and mocks

- Use the real code wherever it is fast and repeatable.
- Fake only at the edge of the system: network, outside services, clock, randomness, slow or costly resources.
- Prefer a simple working fake (for example an in-memory store) over mocks that assert which internal calls happened.
- A test that needs many mocks is a sign the code mixes logic with input and output. Fix the design rather than adding mocks.

## Reliable tests

- No fixed sleeps. Wait for a condition, with a timeout.
- No dependence on test order, shared state, the real clock, time zone, locale, or network. Fix the clock and the random seed.
- Each test creates and removes its own data. Tests that run in parallel use their own ports, files, and IDs.

## Check the test

- Break the code on purpose: invert a condition or remove a line. If the test still passes, it is weak; fix the test.
- Run the whole required suite, not only the new test.
