"""Only product-created immutable fixture inputs may enter the coding worker."""
import json
import subprocess
from pathlib import Path

from ethen.code.package_inventory import inventory
from ethen.code.qualification import BEFORE, AFTER, TESTS


def validate_workspace(root: Path) -> None:
    repo = root / 'project'
    allowed = {'calc.py', 'test_calc.py', '.env', '.git'}
    if (root / 'evidence/worker-identity.json').exists():
        allowed.add('child.pid')
    if {p.name for p in repo.iterdir()} - allowed:
        raise PermissionError('Unexpected workspace files; arbitrary repository code is not qualified')
    if (repo / '.git').is_symlink() or not (repo / '.git').is_dir():
        raise PermissionError('Shared or symlink Git metadata is forbidden')
    expected = json.loads((root / 'evidence/git-baseline.json').read_text())
    actual = inventory(repo / '.git', {'index'})
    if actual != expected:
        changes = sorted(k for k in actual.keys() | expected.keys() if actual.get(k) != expected.get(k))
        raise PermissionError('Git metadata changed; reconcile before running: ' + ', '.join(changes[:10]))
    index = repo / '.git/index'
    if index.is_symlink() or not index.is_file() or git_read(repo, 'ls-files', '--stage') != (root / 'evidence/git-index-baseline.txt').read_text():
        raise PermissionError('Git index staged content changed; reconcile before running')
    secret = repo / '.env'
    if not secret.is_symlink() or secret.readlink() != root / 'secrets/.env':
        raise PermissionError('Synthetic secret boundary changed')
    for p in (repo / 'calc.py', repo / 'test_calc.py'):
        if not p.is_file() or p.is_symlink():
            raise PermissionError('Fixture source path changed')
    if (repo / 'calc.py').read_text() not in {BEFORE, AFTER} or (repo / 'test_calc.py').read_text() != TESTS:
        raise PermissionError('Only known owned synthetic source is authorized, including on resume')

def git_read(repository: Path, *args: str) -> str:
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(repository.parent / 'home'),
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_OPTIONAL_LOCKS': '0'}
    return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null', '-c',
                                    'core.fsmonitor=false', '-C', str(repository), *args],
                                   env=env, text=True, timeout=10)

