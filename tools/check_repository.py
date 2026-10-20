#!/usr/bin/env python3
"""Portable packaging checks; the Omarchy validator remains authoritative."""
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


def main():
    files = set(subprocess.check_output(
        ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT
    ).decode().split('\0')) - {''}
    errors = []
    for relative in sorted(files):
        path = ROOT / relative
        if path.is_symlink():
            errors.append(f'Symlinks cannot ship in an Omarchy plugin: {relative}')
        if (path.name in {'settings.json', 'attention.json', 'auth.json', 'credentials.json',
                          'model-catalog.json', 'last-sync.json', 'activity.json'}
                or re.fullmatch(r'conversation.*\.json', path.name)
                or path.name == '.env' or (path.name.startswith('.env.') and path.name != '.env.example')
                or any(part in {'.claude', '.codex', '__pycache__', '.venv'} for part in path.parts)):
            errors.append(f'Local state or credentials must not ship: {relative}')
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    for key in ('schemaVersion', 'id', 'name', 'version', 'author', 'license', 'description', 'kinds', 'entryPoints'):
        if not manifest.get(key):
            errors.append(f'Missing manifest metadata: {key}')
    if manifest['schemaVersion'] != 1 or manifest['id'].startswith('omarchy.'):
        errors.append('Invalid schema or reserved plugin ID')
    for entry in manifest['entryPoints'].values():
        path = ROOT / entry
        if Path(entry).is_absolute() or '..' in Path(entry).parts or not path.is_file():
            errors.append(f'Unsafe or missing entry point: {entry}')
    if f'moduleName: "{manifest["id"]}"' not in (ROOT / manifest['entryPoints']['barWidget']).read_text():
        errors.append('The widget moduleName must match the manifest ID')
    if f'"version": "{manifest["version"]}"' not in (ROOT / 'plugin/core.py').read_text():
        errors.append('Codex client version differs from manifest version')
    for required in ('README.md', 'LICENSE', 'SECURITY.md', 'CONTRIBUTING.md', 'CHANGELOG.md', 'preview.png'):
        if not (ROOT / required).is_file():
            errors.append(f'Missing publication file: {required}')
    for relative in sorted(files):
        path = ROOT / relative
        if path.suffix == '.json':
            json.loads(path.read_text())
        if path.suffix != '.md':
            continue
        content = path.read_text()
        links = re.findall(r'\[[^\]]*\]\(([^)]+)\)', content) + re.findall(r'<img[^>]+src="([^"]+)"', content)
        for link in links:
            target = link.split('#', 1)[0]
            if not target or re.match(r'[a-z][a-z0-9+.-]*:', target, re.I):
                continue
            if not (path.parent / unquote(target)).exists():
                errors.append(f'Broken local link in {relative}: {link}')
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print(f'Repository checks passed ({len(files)} files, version {manifest["version"]})')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
