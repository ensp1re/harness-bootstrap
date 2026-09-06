"""Test probe rejection behavior and fixture restoration, not generated wording."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROBE = Path(__file__).resolve().parents[1] / 'scripts/probe.py'

class ProbeTest(unittest.TestCase):
    def test_always_success_runner_is_rejected_and_state_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / 'docs/harness/tasks.json'
            state.parent.mkdir(parents=True)
            original = b'{"schemaVersion":1,"nextId":2,"tasks":[{"id":"F001"}]}\n'
            state.write_bytes(original)
            fake = root / 'fake.py'
            fake.write_text('print(\'{"ok": true}\')\n')
            result = subprocess.run([sys.executable, str(PROBE), '--root', directory,
                                     '--', sys.executable, str(fake)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertFalse(report['ok'])
            self.assertTrue(any(not c['passed'] for c in report['cases']))
            self.assertEqual(state.read_bytes(), original)

    def test_crashed_runner_restores_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / 'docs/harness/tasks.json'
            state.parent.mkdir(parents=True)
            original = b'{"schemaVersion":1,"nextId":1,"tasks":[]}\n'
            state.write_bytes(original)
            result = subprocess.run([sys.executable, str(PROBE), '--root', directory,
                                     '--', str(root/'missing')], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(state.read_bytes(), original)

if __name__ == '__main__':
    unittest.main()
