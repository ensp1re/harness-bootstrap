#!/usr/bin/env python3
"""Count what one task costs under a given runner: commands, refusals, check runs and reviews.

  python3 scripts/measure.py [--runner PATH] [--flag-review]

A scripted agent does four fixed tasks in disposable repositories and follows what the runner prints.
Run it on the previous runner and on the changed one, and compare the numbers: no model is involved.
--flag-review marks the risky task with `--review`, for runners that have no review paths.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
COUNT = [sys.executable, '-c', "import sys; open('docs/runs/count.txt', 'a').write(sys.argv[1] + '\\n')"]
CONFIG = {'schemaVersion': 2, 'delivery': {'mode': 'local'}, 'review': {'paths': ['src/billing/*']}, 'checks': [
    {'id': 'docs', 'argv': COUNT + ['docs'], 'required': True, 'precommit': True},
    {'id': 'lint', 'argv': COUNT + ['lint'], 'required': True, 'precommit': True, 'paths': ['src/*']},
    {'id': 'unit', 'argv': COUNT + ['unit'], 'required': True, 'paths': ['src/*', 'tests/*']}]}
SCENARIOS = {
    'docs typo': {'edit': 'README.md'},
    'code fix, then a README edit after verify': {'edit': 'src/app.py', 'late': 'README.md'},
    'risky change: one failed review, a fix, then a README edit': {
        'edit': 'src/billing/total.py', 'late': 'README.md', 'reviews': ['fail', 'pass'], 'risky': True},
    'code change outside the review paths': {'edit': 'src/ui/label.py'},
}


def scenario(runner, flag_review, edit, late=None, reviews=(), risky=False):
    with tempfile.TemporaryDirectory(prefix='harness-measure-') as directory:
        root, counts = Path(directory), {'commands': 0, 'refused': 0, 'reviews': 0}
        (root / 'scripts').mkdir()
        (root / 'docs').mkdir()
        shutil.copy(runner, root / 'scripts/harness.py')
        (root / 'docs/config.json').write_text(json.dumps(CONFIG))
        (root / 'docs/tasks.json').write_text(json.dumps({'schemaVersion': 2, 'nextId': 1, 'tasks': []}))
        (root / '.gitignore').write_text('docs/runs/\ndocs/.harness.lock\n')

        def git(*args):
            subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.com', *args], cwd=root,
                           check=True, capture_output=True)

        def harness(*args):
            result = subprocess.run([sys.executable, 'scripts/harness.py', *args], cwd=root, capture_output=True, text=True)
            counts['commands'] += 1
            counts['refused'] += result.returncode != 0
            return result.returncode, result.stdout + result.stderr

        def change(name, text):
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text)

        git('init', '-q', '-b', 'main')
        git('add', '-A')
        git('commit', '-q', '-m', 'initial')
        harness('add', 'the task', *(['--review'] if risky and flag_review else []))
        if harness('start', 'F001')[0]:  # a runner that wants acceptance lines and an own check before work starts
            harness('edit', 'F001', '--accept', 'works', '--check', 'docs')
            harness('start', 'F001')
        change(edit, 'first version\n')
        proof, reviews = [], list(reviews)
        code, out = harness('verify', 'F001')
        if late and not reviews:
            change(late, 'a later edit\n')
            late = None
        for _ in range(12):
            if 'independent review' in out:
                result = reviews.pop(0) if reviews else 'pass'
                harness('review', 'F001', f'--{result}', '--summary', 'scripted', *proof)
                counts['reviews'] += 1
                if result == 'fail':
                    change(edit, 'fixed version\n')
                    code, out = harness('verify', 'F001', *proof)
                    continue
                if late:
                    change(late, 'a later edit\n')
                    late = None
            git('add', '-A')
            git('commit', '-q', '--allow-empty', '-m', 'work')
            code, out = harness('done', 'F001', *proof)
            if code == 0:
                break
            if '--proof' in out and not proof:
                proof, out = ['--proof', '1=docs: scripted'], ''
            elif 'independent review' not in out and 'verify' in out:
                code, out = harness('verify', 'F001', *proof)
            elif 'independent review' not in out:
                raise SystemExit(f'the scripted agent cannot follow: {out}')
        else:
            raise SystemExit('the task never finished')
        harness('wrapup', '--note', 'done')
        ran = (root / 'docs/runs/count.txt').read_text().split() if (root / 'docs/runs/count.txt').exists() else []
        return dict(counts, **{f'{check} runs': ran.count(check) for check in ('unit', 'lint', 'docs')})


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--runner', type=Path, default=SKILL / 'assets/harness.py')
    parser.add_argument('--flag-review', action='store_true')
    args = parser.parse_args()
    print(json.dumps({name: scenario(args.runner.resolve(), args.flag_review, **steps) for name, steps in SCENARIOS.items()}, indent=2))


if __name__ == '__main__':
    main()
