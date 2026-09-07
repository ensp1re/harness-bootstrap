# Reliability and recovery

Runner state is written with a lock and atomic replacement. A verification attempt is recorded as
`running` before its checks execute; an unfinished attempt is reported as interrupted on the next
state read. Check output is kept in the local run directory. Evidence includes a fingerprint of
the configured inputs and becomes stale when those inputs or the check configuration change.

The runner does not claim recovery for external product side effects. Product work remains queued
until it has its own independent checks.
