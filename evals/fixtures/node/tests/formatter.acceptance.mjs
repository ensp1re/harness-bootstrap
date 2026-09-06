import assert from 'node:assert/strict';
import { formatJson } from '../src/format-json.mjs';

assert.equal(formatJson({ b: 1, a: [true, null] }), '{\n  "b": 1,\n  "a": [\n    true,\n    null\n  ]\n}\n');
let invalid = false;
try { formatJson('{broken'); } catch { invalid = true; }
assert.equal(invalid, true);
console.log('formatter acceptance passed');
