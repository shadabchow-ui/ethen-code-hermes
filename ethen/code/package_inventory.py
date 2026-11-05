"""Conservative rollback of one unchanged, explicitly installed local prefix."""
import hashlib
import json
from pathlib import Path


def inventory(root: Path, excluded=()) -> dict:
    entries = {}
    for p in sorted(root.rglob('*')):
        name = str(p.relative_to(root))
        if name in excluded:
            continue
        if p.is_symlink():
            entries[name] = ['link', str(p.readlink())]
        elif p.is_file():
            entries[name] = ['file', hashlib.sha256(p.read_bytes()).hexdigest()]
        elif p.is_dir():
            entries[name] = ['dir']
        else:
            raise ValueError(f'Unsupported install object: {name}')
    return entries


def uninstall(prefix: Path) -> None:
    if not prefix.is_absolute() or prefix.resolve() != prefix:
        raise ValueError('Owned absolute nonsymlink installation prefix required')
    marker = prefix / 'installed-files.json'
    expected = json.loads(marker.read_text())
    if inventory(prefix, {'installed-files.json'}) != expected:
        raise PermissionError('Installation changed; preserve and reconcile unknown files before rollback')
    if any(p.is_mount() for p in prefix.rglob('*')):
        raise PermissionError('Nested mount in installation')
    for name in sorted(expected, key=lambda n: (n.count('/'), n), reverse=True):
        p = prefix / name
        if p.resolve().is_relative_to(prefix) or p.is_symlink():
            p.rmdir() if expected[name][0] == 'dir' else p.unlink()
        else:
            raise PermissionError('Invalid rollback path')
    marker.unlink()
    prefix.rmdir()
