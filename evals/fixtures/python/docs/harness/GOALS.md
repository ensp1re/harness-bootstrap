# Harness goals

The durable goal is to add a Python CLI that checks CSV headers. This bootstrap records the work
contract and verification plumbing only. Product behavior remains queued until an independent
product check defines and passes the header semantics.

The harness must preserve project instructions, keep task state recoverable, and refuse to treat a
passing harness-plumbing check as product acceptance.
