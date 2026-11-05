"""Linux qualification launcher: positive read allowlist, private network, no secrets.

Invoke only through rootlesskit + unshare in an operator-owned resource scope.
The setup process creates owned synthetic fixtures before restricting itself.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from ethen.code.qualification import require_runtime_isolation


def require_confinement(root: Path) -> dict:
    facts = require_runtime_isolation(root.parent / (root.name + '-forbidden-write'))
    for secret in (root / 'project/.env', root / 'sibling/private.txt'):
        try:
            secret.read_bytes()
        except PermissionError:
            continue
        raise PermissionError('Kernel secret/cross-session read denial missing')
    return facts


def enter(root: Path, resume: bool = False, mode: str = "success") -> None:
    from ethen.code.workflow import prepare

    if not resume:
        prepare(root)
    os.umask(0o077)
    source = Path(__file__).resolve().parents[2]
    python = Path(sys.executable).absolute()
    venv = Path(sys.prefix).resolve()
    group = Path('/proc/self/cgroup').read_text().strip().split(':')[-1]
    read = [source, venv, python, Path('/usr/bin'), Path('/usr/lib'), Path('/usr/share'),
            Path('/lib'), Path('/lib64'), root / 'home', root / 'evidence',
            root / 'project', root / 'issue.json',
            Path('/proc/self'), Path('/proc/net/route'), Path('/proc/net/dev'),
            Path('/sys/fs/cgroup') / group.lstrip('/')]
    read += [Path('/etc') / n for n in ('ld.so.cache', 'localtime', 'nsswitch.conf', 'hosts',
                                       'resolv.conf', 'passwd', 'group')]
    read += [Path('/dev') / n for n in ('null', 'urandom', 'random')]
    args = ['/usr/bin/setpriv', '--no-new-privs', '--landlock-access', 'fs']
    for path in read:
        if path.exists():
            args += ['--landlock-rule', 'path-beneath:' + ('read-file,read-dir,execute:' if path.is_dir() else 'read-file,execute:') + str(path)]
    args += ['--landlock-rule', 'path-beneath:read-dir:' + str(root / 'project')]
    writes = 'write-file,remove-dir,remove-file,make-dir,make-reg,make-sock,make-fifo,make-sym,refer,truncate'
    for path in (root / 'home', root / 'evidence', root / 'project'):
        args += ['--landlock-rule', 'path-beneath:' + writes + ':' + str(path)]
    args += ['--landlock-rule', 'path-beneath:write-file:/dev/null', str(python),
             '-m', 'ethen.code.isolation', '--run', str(root), mode]
    env = {'PATH': str(Path(sys.executable).parent) + ':/usr/bin:/bin', 'HOME': str(root / 'home'),
           'HERMES_HOME': str(root / 'home'), 'PYTHONDONTWRITEBYTECODE': '1',
           'TERMINAL_CWD': str(root / 'project'), 'TERMINAL_ENV': 'local',
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
           'GIT_TEMPLATE_DIR': str(root / 'home/git-template'), 'LANG': 'C.UTF-8', 'TZ': 'UTC', 'TMPDIR': str(root / 'home/tmp')}
    os.execve(args[0], args, env)


if __name__ == '__main__':
    if len(sys.argv) not in (3, 4) or sys.argv[1] not in {'--prepare', '--resume', '--run'}:
        raise SystemExit('Use --prepare/--run with an owned absolute output path')
    mode = sys.argv[3] if len(sys.argv) == 4 else "success"
    if mode not in {"success", "cancel", "crash", "interactive"}:
        raise SystemExit("Unknown qualification mode")
    root = Path(sys.argv[2])
    if not root.is_absolute() or root.is_symlink():
        raise SystemExit('Owned absolute nonsymlink path required')
    if sys.argv[1] in {'--prepare', '--resume'}:
        enter(root, resume=sys.argv[1] == '--resume', mode=mode)
    else:
        require_confinement(root)
        from ethen.code.workflow import run
        run(root, mode='success' if mode == 'interactive' else mode, interactive=mode == 'interactive')
