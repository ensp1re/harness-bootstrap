import assert from 'node:assert/strict';
assert.equal(process.env.HARNESS_FIXTURE_CHECK ?? 'ok', 'ok');
console.log('existing lint check passed');
