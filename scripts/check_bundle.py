#!/usr/bin/env python3
"""Check that the skill bundle is complete and its documents match the runner. Run before publishing."""
import json
import re
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
errors = []
REQUIRED = ('SKILL.md', 'assets/harness.py', 'assets/agents-block.md', 'assets/templates/PROJECT.md.tmpl',
            'assets/templates/RESEARCH.md.tmpl', 'references/discovery.md', 'references/harness.md',
            'scripts/bootstrap.py', 'tests/test_harness.py', 'tests/test_audit.py', 'assets/workflow.md', 'assets/check_docs.py')

for name in REQUIRED:
    if not (root / name).is_file():
        errors.append(f'missing {name}')

skill = (root / 'SKILL.md').read_text(encoding='utf-8')
front = re.match(r'^---\n(.*?)\n---\n', skill, re.S)
fields = dict(line.split(':', 1) for line in front.group(1).splitlines() if ':' in line) if front else {}
description = fields.get('description', '').strip()
if fields.get('name', '').strip() != 'harness-bootstrap':
    errors.append('SKILL.md: name must be harness-bootstrap')
if not description or len(description) > 1024 or '<' in description or '>' in description:
    errors.append('SKILL.md: description must be 1-1024 characters without angle brackets')
if len(skill.splitlines()) > 500:
    errors.append('SKILL.md: keep the body under 500 lines')

for name in [str(path.relative_to(root)) for folder in ('assets', 'scripts', 'tests') for path in (root / folder).rglob('*.py')]:
    try:
        compile((root / name).read_text(encoding='utf-8'), name, 'exec')
    except (SyntaxError, OSError) as error:
        errors.append(f'{name}: {error}')

help_text = subprocess.run([sys.executable, str(root / 'assets/harness.py'), '-h'], capture_output=True, text=True)
commands = set(re.findall(r'^ {4}([a-z]+) ', help_text.stdout, re.M)) if help_text.returncode == 0 else set()
if not commands:
    errors.append('assets/harness.py -h did not list commands')
block = (root / 'assets/agents-block.md').read_text(encoding='utf-8')
if not block.startswith('<!-- harness:start') or not block.rstrip().endswith('<!-- harness:end -->'):
    errors.append('assets/agents-block.md: must start and end with the harness markers')
for name in ('assets/workflow.md', 'assets/agents-block.md', 'references/harness.md', 'SKILL.md', 'references/discovery.md'):
    for command in re.findall(r'`([a-z]+) (?:ID|F0|"|<)', (root / name).read_text(encoding='utf-8')):
        if commands and command not in commands and command not in {'grep', 'python3', 'note'} | commands:
            errors.append(f'{name}: documents unknown runner command {command!r}')

for path in root.rglob('*.md'):
    if '.git' in path.parts:
        continue
    for link in re.findall(r'\]\(([^)\s]+)\)', path.read_text(encoding='utf-8')):
        if '://' in link or link.startswith(('#', 'mailto:')) or '<' in link:
            continue
        # These assets are installed at different destinations; fixture probes check their live links.
        if path.relative_to(root).as_posix() in ('assets/agents-block.md', 'assets/workflow.md'):
            if path.name == 'agents-block.md' and link == 'docs/workflow.md':
                continue
        if not (path.parent / link.split('#')[0]).exists():
            errors.append(f'{path.relative_to(root)}: broken link {link}')

print(json.dumps({'ok': not errors, 'runnerCommands': sorted(commands), 'errors': errors}, indent=2))
sys.exit(1 if errors else 0)
