"""Only product-created immutable fixture inputs may enter the coding worker."""
import json
from pathlib import Path

from ethen.code.package_inventory import inventory


def validate_workspace(root: Path) -> None:
    repo = root / 'project'
    allowed = {'calc.py', 'test_calc.py', '.env', '.git'}
    if (root / 'evidence/worker-identity.json').exists():
        allowed.add('child.pid')
    if {p.name for p in repo.iterdir()} - allowed:
        raise PermissionError('Unexpected workspace files; arbitrary repository code is not qualified')
    if (repo / '.git').is_symlink() or not (repo / '.git').is_dir():
        raise PermissionError('Shared or symlink Git metadata is forbidden')
    if inventory(repo / '.git') != json.loads((root / 'evidence/git-baseline.json').read_text()):
        raise PermissionError('Git metadata changed; reconcile before running')
    secret = repo / '.env'
    if not secret.is_symlink() or secret.readlink() != root / 'secrets/.env':
        raise PermissionError('Synthetic secret boundary changed')
    for p in (repo / 'calc.py', repo / 'test_calc.py'):
        if not p.is_file() or p.is_symlink():
            raise PermissionError('Fixture source path changed')
