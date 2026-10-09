#!/usr/bin/env python3
"""Check local Markdown links and the canonical project decision register."""
import re
import sys
from pathlib import Path
from urllib.parse import unquote


def check(root):
    errors, decisions = [], {}
    files = [root / 'AGENTS.md', *sorted((root / 'docs').rglob('*.md'))]
    for path in files:
        if not path.is_file() or 'runs' in path.relative_to(root).parts:
            continue
        text = path.read_text(encoding='utf-8')
        fenced = False
        for number, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith(('```', '~~~')):
                fenced = not fenced
            if fenced:
                continue
            for link in re.findall(r'\]\(([^)\s]+)\)', line):
                target = unquote(link.split('#', 1)[0])
                if target and not re.match(r'\w+:', target) and '<' not in target and not (path.parent / target).exists():
                    errors.append(f'{path.relative_to(root)}:{number}: broken link {link}')
            match = re.match(r'\|\s*(D-\d+)\s*\|', line)
            if match:
                ident = match[1]
                if ident in decisions:
                    errors.append(f'{path.relative_to(root)}:{number}: duplicate decision {ident}')
                if path != root / 'docs/PROJECT.md':
                    errors.append(f'{path.relative_to(root)}:{number}: {ident} belongs in docs/PROJECT.md')
                decisions[ident] = path
    return errors


def main():
    root = Path(__file__).resolve().parents[1]
    errors = check(root)
    for error in errors:
        print(error)
    print(f'docs-check: {len(errors)} errors')
    return bool(errors)


if __name__ == '__main__':
    sys.exit(main())
