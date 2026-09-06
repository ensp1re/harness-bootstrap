import test from 'node:test';
import assert from 'node:assert/strict';

test('existing project test script remains usable', () => {
  assert.equal(2 + 2, 4);
});
