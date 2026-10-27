"""One-way source sync and pinned, isolated upstream setup. Run with WSL Python."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def call(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def ignored_secrets(directory, names):
    return {name for name in names if name == '__pycache__' or
            name.lower() == '.env' or name.lower().startswith('.env.')}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--root', type=Path, default=Path.home() / 'projects/harness2_portable_core')
    parser.add_argument('--setup', action='store_true', help='fetch pinned upstreams and install isolated environments')
    parser.add_argument('--build', action='store_true', help='prepare context and build Linux image')
    args = parser.parse_args()
    if os.name != 'posix':
        parser.error('run inside WSL/Linux with Python 3.12 or 3.13')
    source, root = args.source.resolve(), args.root.expanduser().resolve()
    project = root / 'project'
    project.mkdir(parents=True, exist_ok=True)
    owned = project / '.source-sync.json'
    old = json.loads(owned.read_text()) if owned.exists() else {}
    for name, expected in old.items():
        dest = project / name
        if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f'execution mirror edited: {dest}; reconcile it before syncing')
    names = [p.relative_to(source) for directory in ('src', 'tests', 'fixtures', 'scripts')
             for p in (source / directory).rglob('*')
             if not any(part.lower() == '.env' or part.lower().startswith('.env.') for part in p.parts)
             and p.is_file() and '__pycache__' not in p.parts and not p.name.endswith('.pyc')]
    names += [Path(n) for n in ('pyproject.toml', 'Dockerfile', 'upstream.lock.json', 'image.lock.json',
                                'build-requirements.in', 'build-constraints.txt', '.dockerignore')]
    manifest = {}
    for relative in names:
        src, dest = source / relative, project / relative
        if src.is_symlink():
            raise RuntimeError(f'source symlink is unsupported: {src}')
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        manifest[relative.as_posix()] = hashlib.sha256(src.read_bytes()).hexdigest()
    for removed in set(old) - set(manifest):
        dest = (project / removed).resolve()
        if not dest.is_relative_to(project) or not dest.is_file():
            raise RuntimeError(f'unexpected stale mirror path: {dest}')
        dest.unlink()  # Only a previously recorded, unchanged file in this mirror.
    owned.write_text(json.dumps(manifest, indent=2) + '\n')
    pins = json.loads((source / 'upstream.lock.json').read_text())
    uv = root / '.tools/bin/uv'
    constraints = str(project / 'build-constraints.txt')
    if args.setup:
        if not uv.is_file():
            raise RuntimeError(f'install project-scoped uv at {uv}; see SETUP.md')
        for name, pin in pins.items():
            checkout = root / 'upstream' / name
            if not checkout.exists():
                checkout.parent.mkdir(parents=True, exist_ok=True)
                call('git', 'clone', pin['url'], str(checkout))
            if subprocess.check_output(['git', 'remote', 'get-url', 'origin'], cwd=checkout, text=True).strip() != pin['url']:
                raise RuntimeError(f'unexpected origin at {checkout}')
            if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=checkout, text=True).strip():
                raise RuntimeError(f'upstream checkout has modifications: {checkout}')
            extra = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard'], cwd=checkout, text=True).splitlines()
            if any(not any(part in {'__pycache__', 'build'} or part.endswith('.egg-info') for part in Path(item).parts) for item in extra):
                raise RuntimeError(f'upstream checkout has unexpected untracked files: {checkout}')
            call('git', 'checkout', '--detach', pin['commit'], cwd=checkout)
            if not (checkout / '.venv/bin/python').exists():
                call(str(uv), 'venv', '--python', '3.12', '.venv', cwd=checkout)
            call(str(uv), 'pip', 'install', '--build-constraints', constraints,
                 '--python', str(checkout / '.venv/bin/python'), '-e', str(checkout))
        if not (project / '.venv/bin/python').exists():
            call(str(uv), 'venv', '--python', '3.12', '.venv', cwd=project)
        call(str(uv), 'pip', 'install', '--build-constraints', constraints,
             '--python', str(project / '.venv/bin/python'), '-e', str(project), '-e', str(root / 'upstream/cli'))
    if args.build:
        checkout = root / 'upstream/cli'
        if subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout, text=True).strip() != pins['cli']['commit']:
            raise RuntimeError('CLI checkout differs from pinned revision')
        context_key = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()[:12]
        context = root / 'build-context' / context_key
        context.mkdir(parents=True, exist_ok=True)
        for relative in names:
            if relative.parts[0] in {'src', 'fixtures'}:
                destination = context / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(project / relative, destination)
        shutil.copyfile(project / 'Dockerfile', context / 'Dockerfile')
        shutil.copyfile(project / '.dockerignore', context / '.dockerignore')
        if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=checkout, text=True).strip():
            raise RuntimeError('CLI checkout has tracked modifications; refusing an unpinned build')
        shutil.copytree(checkout / 'harness2', context / 'upstream-cli/harness2', dirs_exist_ok=True, ignore=ignored_secrets)
        shutil.copyfile(checkout / 'LICENSE', context / 'upstream-cli/LICENSE')
        call(str(uv), 'build', '--wheel', '--build-constraints', constraints, '--require-hashes',
             '--out-dir', str(context / 'wheels'), str(checkout))
        call(str(uv), 'build', '--wheel', '--build-constraints', constraints, '--require-hashes',
             '--out-dir', str(context / 'wheels'), str(project))
        base = json.loads((source / 'image.lock.json').read_text())['python_image']
        call('docker', 'build', '--build-arg', f'PYTHON_IMAGE={base}', '-t', 'h2portable:offline', str(context))
    print(json.dumps({'source': str(source), 'execution_mirror': str(project), 'synced_files': len(manifest)}))


if __name__ == '__main__':
    main()
