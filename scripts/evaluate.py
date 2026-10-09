#!/usr/bin/env python3
"""Prove regression probes catch selected false-success mutations in disposable copies."""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MUTATIONS = [
    ('changed-inputs', "passed = not changed and all(result['outcome'] == 'passed' for result in results)",
     "passed = all(result['outcome'] == 'passed' for result in results)",
     'test_audit.EvidenceAudit.test_source_mutation_during_checks_fails'),
    ('arbitrary-proof', "if text.strip().split(':', 1)[0] not in checks:", 'if False:',
     'test_audit.EvidenceAudit.test_proof_must_name_executed_check_and_unique_criterion'),
    ('absent-ci', "return 'pending', [{'name': 'CI checks have not been reported'}]", "return 'pass', []",
     'test_audit.DeliveryAudit.test_absent_or_non_success_ci_does_not_merge'),
    ('skip-package-validation', '            package_command(root, check)', '            pass',
     'test_generated.GeneratedProbe.test_missing_pnpm_filtered_script_never_executes_fake_success'),
    ('skip-commit-hooks', "'commit', '--quiet', '-m', f'chore: mark", "'commit', '--quiet', '--no-verify', '-m', f'chore: mark",
     'test_generated.GeneratedProbe.test_delivery_commit_runs_precommit_hooks'),
    ('unbound-task-constraints', 'if version >= 3:', 'if False:',
     'test_audit.EvidenceAudit.test_all_task_constraints_invalidate_verification'),
]


def main():
    failed = []
    for name, old, new, test in MUTATIONS:
        with tempfile.TemporaryDirectory(prefix='harness-mutation-') as directory:
            copy = Path(directory)
            for folder in ('assets', 'scripts', 'tests'):
                shutil.copytree(ROOT / folder, copy / folder, ignore=shutil.ignore_patterns('__pycache__'))
            runner = copy / 'assets/harness.py'
            source = runner.read_text()
            if source.count(old) != 1:
                raise SystemExit(f'{name}: mutation anchor is missing or ambiguous')
            runner.write_text(source.replace(old, new))
            result = subprocess.run([sys.executable, '-m', 'unittest', test], cwd=copy / 'tests',
                                    capture_output=True, text=True)
            # Import/syntax/tool errors do not count as a test catching a false success.
            caught = result.returncode != 0 and 'FAIL:' in result.stderr and 'ERROR:' not in result.stderr
            print(f'{name}: {"caught" if caught else "NOT CAUGHT"}', flush=True)
            if not caught:
                failed.append(name)
                print(result.stdout + result.stderr)
    print(f'{len(MUTATIONS) - len(failed)}/{len(MUTATIONS)} mutations caught')
    return bool(failed)


if __name__ == '__main__':
    sys.exit(main())
