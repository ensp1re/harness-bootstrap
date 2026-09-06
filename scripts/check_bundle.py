#!/usr/bin/env python3
"""Validate bundled template references and local documentation links."""
import json
from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parents[1]
templates = root / 'assets/templates'
manifest = json.loads((templates / 'manifest.json').read_text())
variables = {v for group in manifest['variables'].values() for v in group}
errors = []
ids = set()
for item in manifest['templates']:
    if item['id'] in ids:
        errors.append(f"Duplicate template ID: {item['id']}")
    ids.add(item['id'])
    path = templates / item['source']
    if not path.is_file():
        errors.append(f'Missing template: {path.name}')
        continue
    used = set(re.findall(r'\{\{([A-Z_]+)\}\}', path.read_text()))
    if used - variables:
        errors.append(f'{path.name}: undeclared variables {sorted(used - variables)}')
    if item['destinationVariable'] not in variables:
        errors.append(f'{path.name}: undeclared destination')
for path in root.rglob('*.md'):
    for link in re.findall(r'\]\(([^)]+)\)', path.read_text()):
        if '://' in link or link.startswith('#'):
            continue
        if not (path.parent / link.split('#')[0]).exists():
            errors.append(f'{path.relative_to(root)}: missing {link}')
print(json.dumps({'ok': not errors, 'templates': len(ids), 'errors': errors}, indent=2))
sys.exit(bool(errors))
