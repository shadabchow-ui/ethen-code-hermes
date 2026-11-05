"""Ethen Code local synthetic CLI; delegates execution to confined native Hermes."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def selected(session: Path, repository: Path) -> Path:
    if not session.is_absolute() or session.resolve() != session or session.stat().st_uid != os.getuid():
        raise PermissionError('Select an owned absolute session')
    if repository.is_symlink() or repository.absolute() != session / 'project':
        raise PermissionError('Only this session\'s disposable repository is authorized')
    from ethen.code.product_workspace import validate_workspace
    validate_workspace(session)
    issue = json.loads((session / 'issue.json').read_text())
    if issue.get('repository') != str(repository) or issue.get('id') != 'owned-issue':
        raise PermissionError('Repository assignment mismatch')
    if not (session / 'evidence/budget.db').exists():
        from ethen.code.qualification import BEFORE, TESTS
        if (repository / 'calc.py').is_symlink() or (repository / 'test_calc.py').is_symlink():
            raise PermissionError('Fixture source symlink')
        if (repository / 'calc.py').read_text() != BEFORE or (repository / 'test_calc.py').read_text() != TESTS:
            raise PermissionError('Only unchanged owned fixture source is qualified')
        if fixture_git(repository, 'status', '--porcelain', '--untracked-files=no').strip():
            raise PermissionError('Dirty fixture baseline')
        if fixture_git(repository, 'remote').strip():
            raise PermissionError('Disposable fixture must have no remotes')
    return repository


def fixture_git(repository: Path, *args: str) -> str:
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(repository.parent / 'home'),
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null'}
    return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null', '-c',
                                    'core.fsmonitor=false', '-C', str(repository), *args],
                                   env=env, text=True, timeout=10)


from ethen.code.product_processes import stop, worker


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Ethen Code: local, zero-spend Hermes synthetic sessions')
    parser.add_argument('command', choices=['init', 'run', 'resume', 'receipt', 'stop'])
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--repo', type=Path)
    parser.add_argument('--scenario', choices=['interactive', 'cancel', 'crash'], default='interactive',
                        help='cancel/crash are owned fault-injection diagnostics')
    args = parser.parse_args(argv)
    root = args.session
    try:
        if not sys.platform.startswith('linux'):
            raise RuntimeError('Confined local sessions currently require Linux; no macOS/Windows qualification')
        if not root.is_absolute() or root.is_symlink():
            raise PermissionError('Owned absolute nonsymlink session path required')
        if args.command == 'init':
            result = subprocess.run([sys.executable, '-m', 'ethen.code.product_prepare', str(root)], check=False, timeout=30)
            if result.returncode == 0:
                print(f'Ethen Code disposable repository: {root / "project"}')
            return result.returncode
        selected(root, args.repo or root / 'project')
        if args.command == 'stop':
            stop(root)
            return 0
        if args.command in {'run', 'resume'}:
            code = worker(root, args.scenario)
            if code:
                approval = root / 'evidence/operator-approval.json'
                if approval.exists() and not json.loads(approval.read_text())['allowed']:
                    print('Edit denied. Source preserved; session is fenced against automatic retry.')
                    return 3
                return code
        receipt = root / 'evidence/receipt.json'
        if not receipt.exists():
            receipt = root / 'evidence/cancel-receipt.json'
        print('Ethen Code review receipt\n' + receipt.read_text())
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        print(f'Ethen Code stopped: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
