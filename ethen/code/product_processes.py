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
    import logging
    try:
        return subprocess.run(['systemctl', '--user', 'kill', '--kill-whom=all', f'--signal={signum}', unit],
                              env={'PATH': '/usr/bin:/bin', 'XDG_RUNTIME_DIR': f'/run/user/{os.getuid()}'},
                              capture_output=True, text=True, check=False, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        logging.getLogger(__name__).exception('Owned scope signal failed; preserving session recovery evidence')
        return None


def stop(session: Path) -> None:
    if not session.is_absolute() or session.resolve() != session or session.stat().st_uid != os.getuid():
        raise PermissionError('Owned canonical session required')
    with (session / 'evidence/controller.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            idle_lock = True
        except BlockingIOError:
            idle_lock = False
        stop_session(session, idle_lock)


def stop_session(session, idle_lock):
    unit = unit_record(session)
    record = json.loads((session / 'evidence/worker-identity.json').read_text())
    if record.get('session') != str(session):
        raise PermissionError('Worker belongs to another session or launch')
    from ethen.code.product_idle import owned_unit
    owned_unit(record.get('unit'))
    pid = record['pid']
    if type(pid) is not int or not 0 < pid < 2**31 or not isinstance(record.get('start'), str) or not record['start'].isdigit():
        raise PermissionError('Malformed worker process identity')
    stop_recorded(session, unit, record, idle_lock)


def stop_recorded(session, unit, record, idle_lock):
    try:
        descriptor = os.pidfd_open(record['pid'])
    except ProcessLookupError:
        if not idle_lock:
            raise PermissionError('Controller is active; idle state is not established') from None
        from ethen.code.product_idle import require_absent_scope, require_completed
        require_completed(session)
        for name in {unit['unit'], record['unit']}:
            require_absent_scope(name)
        require_missing_pid(record['pid'])
        return
    try:
        require_owned_process(unit, record)
        signal.pidfd_send_signal(descriptor, signal.SIGTERM)
    finally:
        os.close(descriptor)


def require_owned_process(unit, record):
    if record['unit'] != unit['unit']:
        raise PermissionError('Worker belongs to another launch')
    pid = record['pid']
    actual = Path('/proc', str(pid), 'stat').read_text().rsplit(')', 1)[1].split()[19]
    if actual != record['start'] or Path('/proc', str(pid)).stat().st_uid != os.getuid():
        raise PermissionError('Stale worker identity; refusing signal')
    from ethen.code.product_idle import require_active_scope
    require_active_scope(unit['unit'], pid)


def require_missing_pid(pid):
    try:
        descriptor = os.pidfd_open(pid)
    except ProcessLookupError:
        return
    os.close(descriptor)
    raise PermissionError('Recorded PID is live or reused; idle state is ambiguous')


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
    process = subprocess.Popen(command, cwd=source, env=env, start_new_session=True)
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
        process.kill()
        process.wait(timeout=15)
