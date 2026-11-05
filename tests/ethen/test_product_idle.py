"""Idle stop never turns stale PID/scope evidence into authority to signal."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from ethen.code import product_idle, product_processes
from ethen.code.product_workspace import git_read
from ethen.code.qualification import AFTER

pytestmark = pytest.mark.platforms('linux')
UNIT = 'ethen-code-' + 'a' * 32 + '.scope'
OLD_UNIT = 'ethen-code-' + 'b' * 32 + '.scope'
REAL_PIDFD_OPEN = os.pidfd_open


@pytest.fixture
def completed(tmp_path, monkeypatch):
    root = tmp_path / 'session'
    result = subprocess.run([sys.executable, '-B', '-m', 'ethen.code.product_prepare', str(root)],
                            check=False, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    repo = root / 'project'
    (repo / 'calc.py').write_text(AFTER)
    receipt = {'schema': 2, 'issue': 'owned-issue', 'native_agent': True, 'session_recovery': True,
               'push_merge_deployment': False, 'test_exit_codes': [1, 0], 'diff_exit': 0,
               'baseline_sha': git_read(repo, 'rev-parse', 'HEAD').strip(),
               'branch': 'work/owned-issue', 'changed_files': ['calc.py']}
    evidence = root / 'evidence'
    (evidence / 'receipt.json').write_text(json.dumps(receipt))
    (evidence / 'controller-unit.json').write_text(json.dumps({'session': str(root), 'unit': UNIT}))
    (evidence / 'worker-identity.json').write_text(json.dumps({'session': str(root), 'unit': OLD_UNIT,
                                                            'pid': 99999999, 'start': '1'}))
    with sqlite3.connect(evidence / 'budget.db') as db:
        db.execute('CREATE TABLE reservations(request TEXT,state TEXT)')
        db.execute('CREATE TABLE receipts(request TEXT,payload TEXT)')
        db.execute('INSERT INTO reservations VALUES (?,?)', ('owned-issue-attempt-1', 'completed'))
        db.execute('INSERT INTO receipts VALUES (?,?)', ('owned-issue-attempt-1', json.dumps(receipt)))
    with sqlite3.connect(evidence / 'session.db') as db:
        db.execute('CREATE TABLE messages(session_id TEXT,role TEXT)')
        db.execute('INSERT INTO messages VALUES (?,?)', ('owned-issue', 'tool'))

    def missing(_):
        raise ProcessLookupError('Owned historical PID is gone')

    monkeypatch.setattr(product_processes.os, 'pidfd_open', missing)
    monkeypatch.setattr(product_idle, 'scope_status', lambda unit: {
        'Id': unit, 'LoadState': 'not-found', 'ActiveState': 'inactive', 'ControlGroup': ''})
    monkeypatch.setattr(product_processes.signal, 'pidfd_send_signal', lambda *args: pytest.fail('Idle stop signaled'))
    return root


def test_completed_resume_and_repeated_stop_leave_receipts_unchanged(completed):
    paths = [completed / 'evidence' / n for n in ['receipt.json', 'budget.db', 'session.db']]
    before = [p.read_bytes() for p in paths]
    product_processes.stop(completed)
    product_processes.stop(completed)
    assert [p.read_bytes() for p in paths] == before


@pytest.mark.parametrize('kind', ['foreign-session', 'bad-unit', 'live-pid', 'pid-reappears'])
def test_foreign_reused_and_racing_identities_are_denied(completed, monkeypatch, kind):
    path = completed / 'evidence/worker-identity.json'
    record = json.loads(path.read_text())
    if kind == 'foreign-session':
        record['session'] = str(completed.parent / 'foreign')
    elif kind == 'bad-unit':
        record['unit'] = 'unrelated.scope'
    else:
        calls = []

        def opened(_):
            calls.append(1)
            if kind == 'pid-reappears' and len(calls) == 1:
                raise ProcessLookupError('Gone before proof')
            return os.open('/dev/null', os.O_RDONLY)

        monkeypatch.setattr(product_processes.os, 'pidfd_open', opened)
    path.write_text(json.dumps(record))
    with pytest.raises(PermissionError):
        product_processes.stop(completed)


@pytest.mark.parametrize('state', ['active', 'activating', 'deactivating', 'failed', 'unknown'])
def test_present_or_unknown_scope_never_becomes_idle(completed, monkeypatch, state):
    monkeypatch.setattr(product_idle, 'scope_status', lambda unit: {
        'Id': unit, 'LoadState': 'loaded', 'ActiveState': state, 'ControlGroup': '/owned'})
    with pytest.raises(PermissionError):
        product_processes.stop(completed)


@pytest.mark.parametrize('state', ['reserved', 'cancelled', 'failed'])
def test_noncompleted_work_is_not_hidden_by_idle_stop(completed, state):
    with sqlite3.connect(completed / 'evidence/budget.db') as db:
        db.execute('UPDATE reservations SET state=?', (state,))
    with pytest.raises(PermissionError):
        product_processes.stop(completed)


@pytest.mark.parametrize('changed', ['receipt', 'history', 'source'])
def test_completion_tampering_is_denied(completed, changed):
    if changed == 'receipt':
        (completed / 'evidence/receipt.json').write_text('{}')
    elif changed == 'history':
        with sqlite3.connect(completed / 'evidence/session.db') as db:
            db.execute('DELETE FROM messages')
    else:
        (completed / 'project/calc.py').write_text('unapproved source\n')
    with pytest.raises(PermissionError):
        product_processes.stop(completed)


@pytest.mark.parametrize('failure', ['timeout', 'bus-error', 'malformed'])
def test_scope_inspection_fails_closed(monkeypatch, failure):
    def query(*args, **kwargs):
        if failure == 'timeout':
            raise subprocess.TimeoutExpired('systemctl', 10)
        return subprocess.CompletedProcess([], 1 if failure == 'bus-error' else 0, stdout='Id=wrong\n')
    monkeypatch.setattr(product_idle.subprocess, 'run', query)
    with pytest.raises((PermissionError, subprocess.TimeoutExpired)):
        product_idle.scope_status(UNIT)


def test_busy_controller_cannot_claim_idle(completed, monkeypatch):
    def busy(*args):
        raise BlockingIOError('Controller still owns launch')
    monkeypatch.setattr(product_processes.fcntl, 'flock', busy)
    with pytest.raises(PermissionError, match='Controller is active'):
        product_processes.stop(completed)


def test_pid_reuse_cannot_signal_a_live_process(completed, monkeypatch):
    path = completed / 'evidence/worker-identity.json'
    record = json.loads(path.read_text())
    record.update(unit=UNIT, pid=os.getpid(), start='0')
    path.write_text(json.dumps(record))
    monkeypatch.setattr(product_processes.os, 'pidfd_open', REAL_PIDFD_OPEN)
    with pytest.raises(PermissionError, match='Stale worker identity'):
        product_processes.stop(completed)


def test_inactive_metadata_without_cgroup_is_idle(completed, monkeypatch):
    monkeypatch.setattr(product_idle, 'scope_status', lambda unit: {
        'Id': unit, 'LoadState': 'loaded', 'ActiveState': 'inactive', 'ControlGroup': ''})
    product_processes.stop(completed)


def test_live_process_outside_owned_scope_is_denied(completed, monkeypatch):
    path = completed / 'evidence/worker-identity.json'
    record = json.loads(path.read_text())
    record.update(unit=UNIT, pid=os.getpid(), start=Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19])
    path.write_text(json.dumps(record))
    monkeypatch.setattr(product_processes.os, 'pidfd_open', lambda pid: os.open('/dev/null', os.O_RDONLY))
    monkeypatch.setattr(product_idle, 'scope_status', lambda unit: {
        'Id': unit, 'LoadState': 'loaded', 'ActiveState': 'active', 'ControlGroup': '/unrelated-scope'})
    with pytest.raises(PermissionError, match='outside its recorded'):
        product_processes.stop(completed)


def test_each_historical_scope_must_independently_be_absent(completed, monkeypatch):
    inspected = []

    def status(unit):
        inspected.append(unit)
        return {'Id': unit, 'LoadState': 'loaded',
                'ActiveState': 'active' if unit == OLD_UNIT else 'inactive',
                'ControlGroup': '/retained-worker' if unit == OLD_UNIT else ''}

    monkeypatch.setattr(product_idle, 'scope_status', status)
    with pytest.raises(PermissionError, match='present or ambiguous'):
        product_processes.stop(completed)
    assert OLD_UNIT in inspected


def test_additional_reserved_dispatch_prevents_idle_success(completed):
    with sqlite3.connect(completed / 'evidence/budget.db') as db:
        db.execute('INSERT INTO reservations VALUES (?,?)', ('owned-issue:provider:pending', 'reserved'))
    with pytest.raises(PermissionError, match='durable completed receipt'):
        product_processes.stop(completed)


@pytest.mark.parametrize('field,value', [('native_agent', False), ('test_exit_codes', [0]),
                                        ('push_merge_deployment', True)])
def test_matching_disk_and_ledger_still_require_qualified_completion(completed, field, value):
    path = completed / 'evidence/receipt.json'
    receipt = json.loads(path.read_text())
    receipt[field] = value
    path.write_text(json.dumps(receipt))
    with sqlite3.connect(completed / 'evidence/budget.db') as db:
        db.execute('UPDATE receipts SET payload=?', (json.dumps(receipt),))
    with pytest.raises(PermissionError, match='not qualified'):
        product_processes.stop(completed)


@pytest.mark.parametrize('name', ['budget.db', 'session.db'])
def test_symlink_database_cannot_supply_idle_proof(completed, name):
    database = completed / 'evidence' / name
    outside = completed.parent / name
    database.rename(outside)
    database.symlink_to(outside)
    with pytest.raises(PermissionError, match='symlink session evidence'):
        product_processes.stop(completed)


def test_real_controller_lock_excludes_idle_proof(completed):
    import fcntl
    with (completed / 'evidence/controller.lock').open('a') as controller:
        fcntl.flock(controller, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(PermissionError, match='Controller is active'):
            product_processes.stop(completed)
