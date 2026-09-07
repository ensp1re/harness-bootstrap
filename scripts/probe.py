#!/usr/bin/env python3
"""Black-box smoke checks for disposable generated-harness fixtures."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('runner', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    runner = args.runner[1:] if args.runner[:1] == ['--'] else args.runner
    if not runner:
        parser.error('provide a runner after --')
    root = Path(args.root).resolve()
    path = root / 'docs/tasks.json'
    original = path.read_bytes()
    state = json.loads(original)
    outcomes = []

    def check(name, command, expected):
        result = subprocess.run(runner + ['--root', str(root)] + command,
                                capture_output=True, text=True, timeout=30)
        try:
            output = json.loads(result.stdout)
            valid = isinstance(output, dict)
        except json.JSONDecodeError:
            valid = False
        passed = result.returncode in expected and valid
        outcomes.append({'case': name, 'passed': passed, 'exit': result.returncode,
                         'diagnostic': '' if passed else (result.stderr + result.stdout)[-1500:]})

    try:
        check('context', ['context'], {0})
        check('valid-state', ['validate'], {0})
        path.write_text('{invalid')
        check('malformed-state', ['validate'], {1, 2})
        path.write_bytes(original)
        if state.get('tasks'):
            duplicate = json.loads(original)
            duplicate['tasks'].append(duplicate['tasks'][0].copy())
            path.write_text(json.dumps(duplicate))
            check('duplicate-id', ['validate'], {1, 2})
            dependency = json.loads(original)
            dependency['tasks'][0]['dependsOn'] = ['F999999']
            path.write_text(json.dumps(dependency))
            check('missing-dependency', ['validate'], {1, 2})
            check('invalid-activation', ['transition', dependency['tasks'][0]['id'], 'active'], {1, 2})
        else:
            outcomes.append({'case': 'task-mutations', 'passed': False,
                             'diagnostic': 'Fixture needs at least one task'})
    finally:
        path.write_bytes(original)
    print(json.dumps({'ok': all(item['passed'] for item in outcomes), 'cases': outcomes}, indent=2))
    return 0 if all(item['passed'] for item in outcomes) else 1


if __name__ == '__main__':
    sys.exit(main())
