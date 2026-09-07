#!/usr/bin/env python3
"""Probe state/evidence invariants on copies of a disposable evaluated fixture."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', required=True)
    ap.add_argument('runner', nargs=argparse.REMAINDER)
    args = ap.parse_args()
    runner = args.runner[1:] if args.runner[:1] == ['--'] else args.runner
    source = Path(args.root).resolve()
    results = []
    for name in ['baseline', 'failed-check', 'missing-executable', 'empty-verification', 'verified-dependency', 'stale-acceptance', 'stale-config', 'handoff-preserves-decisions']:
        with tempfile.TemporaryDirectory(prefix='harness-scenario-') as d:
            root = Path(d) / 'fixture'
            shutil.copytree(source, root, ignore=shutil.ignore_patterns('.git','__pycache__','node_modules'))
            p = root/'docs/tasks.json'
            tasks = json.loads(p.read_text())
            configpath = root/'docs/config.json'
            config = json.loads(configpath.read_text())
            verified = next((t for t in tasks['tasks'] if t['state']=='verified'), None)
            cmd = ['validate']
            expected = {0}
            if name in {'failed-check', 'missing-executable'}:
                task = verified or tasks['tasks'][0]
                for t in tasks['tasks']: t['state']='not_started'
                task['state']='active'
                selected = task['verification'][0] if task.get('verification') else config['checks'][0]['id']
                task['verification']=[selected]
                check = next(c for c in config['checks'] if c['id']==selected)
                check['argv'] = [sys.executable, '-c', 'import sys;sys.exit(9)'] if name=='failed-check' else ['missing-harness-executable-9d137']
                p.write_text(json.dumps(tasks));configpath.write_text(json.dumps(config))
                cmd=['verify',task['id']];expected={1,2}
            elif name == 'empty-verification':
                task = tasks['tasks'][0]
                for t in tasks['tasks']: t['state']='not_started'; t['evidence']=None
                task['state']='active';task['verification']=[]
                p.write_text(json.dumps(tasks));cmd=['verify',task['id']];expected={1,2}
            elif name == 'verified-dependency':
                if verified is None:
                    results.append({'case':name,'passed':False,'reason':'Fixture needs verified task'});continue
                new = dict(tasks['tasks'][0],id=f"F{tasks['nextId']:03d}",state='not_started',dependsOn=[verified['id']],evidence=None)
                tasks['nextId']+=1;tasks['tasks'].append(new)
                p.write_text(json.dumps(tasks));cmd=['transition',new['id'],'active'];expected={1,2}
            elif name == 'stale-acceptance':
                if verified is None:
                    results.append({'case':name,'passed':False,'reason':'Fixture needs verified task'});continue
                verified['acceptance'].append('A new requirement not covered by the prior run')
                p.write_text(json.dumps(tasks));expected={1,2}
            elif name == 'stale-config':
                config['checks'][0]['timeoutSeconds']+=1
                configpath.write_text(json.dumps(config));expected={1,2}
            elif name == 'handoff-preserves-decisions':
                hp=root/'docs/handoff.json'
                handoff=json.loads(hp.read_text());handoff['decisions']=['Preserve this user decision'];hp.write_text(json.dumps(handoff))
                cmd=['handoff']
            # Absolute runner path continues to execute original code against isolated root.
            out=subprocess.run(runner+['--root',str(root)]+cmd,capture_output=True,text=True,timeout=30)
            try: payload=json.loads(out.stdout)
            except json.JSONDecodeError: payload=None
            passed=out.returncode in expected and isinstance(payload,dict)
            if name in {'failed-check','missing-executable','empty-verification'}:
                final=json.loads(p.read_text())
                passed=passed and all(t['state'] not in {'verified','passing'} for t in final['tasks'])
            if name=='handoff-preserves-decisions':
                passed=passed and json.loads(hp.read_text()).get('decisions')==['Preserve this user decision']
            results.append({'case':name,'passed':passed,'exit':out.returncode,'details':payload if not passed else None})
    print(json.dumps({'ok':all(r['passed'] for r in results),'cases':results},indent=2))
    return int(not all(r['passed'] for r in results))

if __name__=='__main__':sys.exit(main())
