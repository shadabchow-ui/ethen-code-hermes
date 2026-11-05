"""Offline source-prefix installer using Hermes PM and native payload launchers."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from email.parser import Parser


def assemble(source: Path, prefix: Path, python: Path, cache: Path) -> dict:
    import pm
    from scripts.build.agent import write_metadata
    from scripts.build.inputs import project_entries
    from scripts.build.launchers import write_launchers

    repo = prefix / 'repo'
    shutil.copytree(source, repo, symlinks=True)
    executable = pm.build_environment(source=repo, out=prefix / 'env', python=python,
                                      cache=cache, frozen=True, sealed=True, offline=True,
                                      no_install_project=True, explicit=True)
    site = prefix / 'env/lib/python3.14/site-packages'
    (site / 'hermes-agent.pth').write_text(os.path.relpath(repo, site) + '\n')
    write_metadata(repo / 'pyproject.toml', repo)
    entry = project_entries(repo / 'pyproject.toml')['ethen-code']
    write_launchers(prefix, {'ethen-code': entry}, python=str(executable),
                    repo='repo', site=str(site), target='linux-x64')
    provenance = {'format': 'Hermes source-prefix CLI', 'python': sys.version,
                  'uv_lock_sha256': hashlib.sha256((repo / 'uv.lock').read_bytes()).hexdigest(),
                  'pm_lock_sha256': hashlib.sha256((repo / 'pm/lock.json').read_bytes()).hexdigest(),
                  'dependency_install': 'PM frozen sealed offline fresh environment',
                  'external_interpreter': str(python), 'platform': sys.platform,
                  'source': json.loads((repo / 'ethen-package-source.json').read_text()),
                  'desktop': 'NOT_RUN', 'hosted_execution': 'NOT_RUN'}
    provenance['installed_dependencies'] = sorted(
        (Parser().parsestr(p.read_text())['Name'], Parser().parsestr(p.read_text())['Version'])
        for p in site.glob('*.dist-info/METADATA'))
    provenance['external_interpreter_sha256'] = hashlib.sha256(python.resolve().read_bytes()).hexdigest()
    (prefix / 'installation.json').write_text(json.dumps(provenance, indent=2))
    from ethen.code.package_inventory import inventory
    (prefix / 'installed-files.json').write_text(json.dumps(inventory(prefix, {'installed-files.json'}), sort_keys=True))
    return provenance


def install(source: Path, prefix: Path, python: Path, cache: Path) -> dict:
    import logging
    import platform
    from ethen.code.package_inventory import inventory
    if not sys.platform.startswith('linux') or sys.version_info[:2] != (3, 14) or platform.machine() != 'x86_64':
        raise RuntimeError('Qualified package requires Linux x86_64 CPython 3.14')
    if not prefix.is_absolute() or prefix.resolve() != prefix or prefix.exists():
        raise ValueError('Install into a new canonical absolute owned prefix')
    expected = json.loads((source / 'ethen-package-files.json').read_text())
    if inventory(source, {'ethen-package-files.json'}) != expected:
        raise PermissionError('Artifact integrity failure: unexpected or modified source')
    if any(p.is_symlink() and not p.resolve().is_relative_to(source) for p in source.rglob('*')):
        raise PermissionError('Artifact symlink escapes source')
    prefix.mkdir(mode=0o700)
    (prefix / 'installation.json').write_text(json.dumps({'state': 'INSTALLING'}))
    try:
        return assemble(source, prefix, python, cache)
    except BaseException:
        logging.getLogger(__name__).exception('Owned installation failed; preserving rollback inventory')
        (prefix / 'installation.json').write_text(json.dumps({'state': 'FAILED'}))
        (prefix / 'installed-files.json').write_text(json.dumps(inventory(prefix, {'installed-files.json'})))
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['install', 'uninstall'])
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--python', type=Path)
    parser.add_argument('--cache', type=Path)
    args = parser.parse_args(argv)
    source = Path(__file__).resolve().parents[2]
    if args.command == 'uninstall':
        from ethen.code.package_inventory import uninstall
        uninstall(args.prefix)
        return 0
    if args.python is None or args.cache is None:
        parser.error('install requires existing --python and --cache')
    print(json.dumps(install(source, args.prefix, args.python, args.cache), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
