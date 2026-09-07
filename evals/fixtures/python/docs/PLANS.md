# Delivery plan

## Objective

Queue a Python CLI that checks CSV headers while keeping the bootstrap harness restartable.

## Slices

1. Implement the CSV-header behavior and define its observable acceptance cases. This slice is
   queued as `F001`; no product implementation exists yet.
2. Keep the generated harness self-validating and resumable. This plumbing slice is `F002`.

## Checkpoints

The harness records check commands, exit statuses, fingerprints, and handoff state. Product work
cannot be marked ready from the plumbing check.

## Closeout

Product readiness requires an independent product check and the delivery evidence required by the
project's eventual workflow.
