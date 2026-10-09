"""Regression scenarios for false verification, delivery and reconciliation success."""
import hashlib
import json
import unittest
from pathlib import Path
from test_harness import Repo, RemoteRepo, OK, PY, bootstrap


class EvidenceAudit(unittest.TestCase):
    def ready(self, checks=None):
        repo = Repo(self, checks or [{'id': 'ok', 'argv': OK}])
        repo.run('add', 'observable behavior', '--accept', 'works', '--check', 'ok')
        self.assertEqual(repo.run('start', 'F001')[0], 0)
        return repo

    def test_all_task_constraints_invalidate_verification(self):
        for field, value in [('keep', ['src/*']), ('dependsOn', ['F002']), ('refs', ['R-2']),
                             ('review', True), ('spec', 'docs/spec.md'), ('plan', 'docs/plan.md')]:
            with self.subTest(field=field):
                repo = self.ready()
                self.assertEqual(repo.run('verify', 'F001')[0], 0)
                path = repo.root / 'docs/tasks.json'
                data = json.loads(path.read_text())
                data['tasks'][0][field] = value
                repo.write('docs/tasks.json', data)
                self.assertIn('definition changed', repo.run('status')[1])

    def test_source_mutation_during_checks_fails(self):
        repo = self.ready([{'id': 'ok', 'argv': [PY, '-c', "from pathlib import Path; Path('source.py').write_text('changed')"]}])
        code, out = repo.run('verify', 'F001')
        self.assertNotEqual(code, 0, out)
        self.assertEqual(repo.tasks()['F001']['state'], 'active')

    def test_task_mutation_during_checks_fails(self):
        script = "import json; from pathlib import Path; p=Path('docs/tasks.json'); d=json.loads(p.read_text()); d['tasks'][0]['keep']=['src/*']; p.write_text(json.dumps(d))"
        repo = self.ready([{'id': 'ok', 'argv': [PY, '-c', script]}])
        self.assertNotEqual(repo.run('verify', 'F001')[0], 0)

    def test_config_not_excluded_by_fingerprint_paths(self):
        repo = self.ready()
        repo.write('src/a.py', 'pass')
        config = json.loads((repo.root / 'docs/config.json').read_text())
        config['fingerprintPaths'] = ['src']
        repo.write('docs/config.json', config)
        self.assertEqual(repo.run('verify', 'F001')[0], 0)
        config['checks'][0]['argv'] = [PY, '-c', 'raise SystemExit(1)']
        repo.write('docs/config.json', config)
        self.assertIn('changed', repo.run('status')[1])

    def test_proof_must_name_executed_check_and_unique_criterion(self):
        repo = self.ready()
        repo.run('verify', 'F001')
        repo.commit('work')
        for proof in [('1=looks good',), ('1=ok', '1=ok'), ('1=ok', '2=ok')]:
            with self.subTest(proof=proof):
                args = [item for value in proof for item in ('--proof', value)]
                self.assertNotEqual(repo.run('done', 'F001', *args)[0], 0)

    def test_explicit_pr_without_remote_does_not_finish_locally(self):
        repo = self.ready()
        config = json.loads((repo.root / 'docs/config.json').read_text())
        config['delivery'] = {'mode': 'pr'}
        repo.write('docs/config.json', config)
        repo.run('verify', 'F001')
        repo.commit('work')
        self.assertNotEqual(repo.run('done', 'F001', '--proof', '1=ok')[0], 0)
        self.assertNotEqual(repo.tasks()['F001']['state'], 'passing')

    def test_registry_rejects_bad_entries(self):
        bad = [[{'id': 'ok', 'argv': OK}, {'id': 'ok', 'argv': OK}],
               [{'id': '../escape', 'argv': OK}], [{'id': 'ok', 'argv': ['']}],
               [{'id': 'ok', 'argv': OK, 'cwd': '..'}],
               [{'id': 'ok', 'argv': OK, 'required': 'false'}],
               [{'id': 'ok', 'argv': OK, 'timeoutSeconds': -1}],
               [{'id': 'ok', 'argv': OK, 'package': '..', 'script': 'test'}]]
        for checks in bad:
            with self.subTest(checks=checks):
                repo = Repo(self, checks)
                code, out = repo.run('validate')
                self.assertNotEqual(code, 0, out)
                self.assertNotIn('Traceback', out)

    def test_missing_package_script_fails_even_if_command_exits_zero(self):
        repo = self.ready([{'id': 'ok', 'argv': OK, 'package': '.', 'script': 'e2e'}])
        repo.write('package.json', {'scripts': {'test': 'echo test'}})
        self.assertNotEqual(repo.run('verify', 'F001')[0], 0)

    def test_bookkeeping_prefix_does_not_hide_source_files(self):
        repo = self.ready()
        repo.write('docs/tasks.json.schema', 'one')
        repo.run('verify', 'F001')
        repo.write('docs/tasks.json.schema', 'two')
        self.assertIn('files changed', repo.run('status')[1])

    def test_hooks_reject_corrupt_state(self):
        repo = self.ready()
        repo.write('docs/tasks.json', '{broken')
        self.assertNotEqual(repo.run('hook', 'pre-commit')[0], 0)

    def test_cli_and_test_output_are_not_debug_leftovers(self):
        repo = self.ready()
        repo.write('scripts/cli.js', 'console.log("result")\n')
        repo.write('tests/output.test.js', 'console.log("test output")\n')
        code, out = repo.run('wrapup', '--note', 'done')
        self.assertEqual(code, 0, out)


class DeliveryAudit(unittest.TestCase):
    def pending(self, mode='pending'):
        repo = RemoteRepo(self, [{'id': 'ok', 'argv': OK}],
                          delivery={'mode': 'pr', 'checksWaitSeconds': 0, 'autoMerge': True})
        repo.run('add', 'behavior', '--accept', 'works', '--check', 'ok')
        self.assertEqual(repo.run('start', 'F001')[0], 0)
        self.assertEqual(repo.run('verify', 'F001')[0], 0)
        repo.commit('work')
        repo.env['FAKE_GH_CHECKS'] = mode
        return repo

    def test_absent_or_non_success_ci_does_not_merge(self):
        for mode in ('none', 'skipping', 'cancel', 'unknown'):
            with self.subTest(mode=mode):
                repo = self.pending(mode)
                self.assertNotEqual(repo.run('done', 'F001', '--proof', '1=ok')[0], 0)
                self.assertEqual(repo.pull_requests()[0]['state'], 'OPEN')

    def test_pending_delivery_rechecks_current_inputs_and_versions(self):
        for change in ('source', 'config', 'task', 'unversioned'):
            with self.subTest(change=change):
                repo = self.pending()
                self.assertNotEqual(repo.run('done', 'F001', '--proof', '1=ok')[0], 0)
                if change == 'source':
                    repo.write('source.py', 'uncommitted change')
                elif change == 'config':
                    config = json.loads((repo.root / 'docs/config.json').read_text())
                    config['checks'][0]['argv'] = [PY, '-c', 'raise SystemExit(1)']
                    repo.write('docs/config.json', config)
                else:
                    data = json.loads((repo.root / 'docs/tasks.json').read_text())
                    if change == 'task':
                        data['tasks'][0]['keep'] = ['src/*']
                    else:
                        data['tasks'][0]['evidence'].pop('version', None)
                    repo.write('docs/tasks.json', data)
                repo.env['FAKE_GH_CHECKS'] = 'pass'
                self.assertNotEqual(repo.run('done', 'F001')[0], 0)
                self.assertEqual(repo.pull_requests()[0]['state'], 'OPEN')

    def test_merge_requires_explicit_configuration(self):
        repo = self.pending('pass')
        config = json.loads((repo.root / 'docs/config.json').read_text())
        config['delivery'].pop('autoMerge')
        repo.write('docs/config.json', config)
        repo.run('verify', 'F001')
        repo.commit('authorization')
        self.assertNotEqual(repo.run('done', 'F001', '--proof', '1=ok')[0], 0)
        self.assertEqual(repo.pull_requests()[0]['state'], 'OPEN')


class InstallAudit(unittest.TestCase):
    def test_removed_managed_block_stays_removed_after_repeated_reruns(self):
        repo = Repo(self, [])
        bootstrap('install', repo.root)
        repo.write('AGENTS.md', '# user rules\n')
        bootstrap('install', repo.root)
        bootstrap('install', repo.root)
        self.assertEqual((repo.root / 'AGENTS.md').read_text(), '# user rules\n')

    def test_malformed_markers_are_conflicts(self):
        repo = Repo(self, [])
        repo.write('AGENTS.md', '# user rules\n<!-- harness:start broken\n')
        before = (repo.root / 'AGENTS.md').read_bytes()
        self.assertNotEqual(bootstrap('install', repo.root)[0], 0)
        self.assertEqual((repo.root / 'AGENTS.md').read_bytes(), before)
