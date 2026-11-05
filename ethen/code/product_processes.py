"""Owned Linux cgroup lifecycle around the unchanged confined Hermes worker."""
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import uuid


def unit_record(session):
    record = json.loads((session / 'evidence/controller-unit.json').read_text())
    if record['session'] != str(session) or not re.fullmatch(r'ethen-code-[0-9a-f]{32}\.scope', record['unit']):
        raise PermissionError('Controller session identity differs')
    return record


def kill_scope(unit, signum):
    return subprocess.run(['systemctl', '--user', 'kill', '--kill-whom=all', f'--signal={signum}', unit],
                          env={'PATH': '/usr/bin:/bin', 'XDG_RUNTIME_DIR': f'/run/user/{os.getuid()}'},
                          capture_output=True, text=True, check=False, timeout=15)


def stop(session: Path) -> None:
    unit = unit_record(session)
    record = json.loads((session / 'evidence/worker-identity.json').read_text())
    if record.get('session') != str(session) or record.get('unit') != unit['unit']:
        raise PermissionError('Worker belongs to another session or launch')
    pid = record['pid']
    descriptor = os.pidfd_open(pid)
    try:
        actual = Path('/proc', str(pid), 'stat').read_text().rsplit(')', 1)[1].split()[19]
        if actual != record['start'] or Path('/proc', str(pid)).stat().st_uid != os.getuid():
            raise PermissionError('Stale worker identity; refusing signal')
        signal.pidfd_send_signal(descriptor, signal.SIGTERM)
    finally:
        os.close(descriptor)


def worker(session: Path, mode: str) -> int:
    with (session / 'evidence/controller.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        unit = 'ethen-code-' + uuid.uuid4().hex + '.scope'
        (session / 'evidence/controller-unit.json').write_text(json.dumps({'unit': unit, 'session': str(session)}))
        return launch(session, mode, unit)


def launch(session: Path, mode: str, unit: str) -> int:
    source = Path(__file__).resolve().parents[2]
    env = {'PATH': str(Path(sys.executable).parent) + ':/usr/bin:/bin',
           'HOME': str(session / 'home'), 'PYTHONDONTWRITEBYTECODE': '1',
           'LANG': 'C.UTF-8', 'TZ': 'UTC', 'XDG_RUNTIME_DIR': f'/run/user/{os.getuid()}'}
    command = ['systemd-run', '--user', '--scope', '--unit', unit, '--quiet', '-p', 'MemoryMax=2200M',
               '-p', 'MemorySwapMax=0', '-p', 'CPUQuota=170%',
               'rootlesskit', '--net=host', 'unshare', '--net', 'bash', '-c',
               'ip link set lo up; exec "$@"', '_', sys.executable,
               '-m', 'ethen.code.isolation', '--resume', str(session), mode]
    with subprocess.Popen(command, cwd=source, env=env, start_new_session=True) as process:
        try:
            return process.wait(timeout=150)
        except (KeyboardInterrupt, subprocess.TimeoutExpired):
            cancel_owned(session, process, unit)
            return 130


def cancel_owned(session, process, unit):
    import logging
    try:
        stop(session)
    except (OSError, ValueError, KeyError):
        logging.getLogger(__name__).exception('Native worker not ready; stopping this owned scope')
        kill_scope(unit, 'SIGTERM')
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        kill_scope(unit, 'SIGKILL')
        process.wait(timeout=15)
