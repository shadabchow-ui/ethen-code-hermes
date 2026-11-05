"""Read-only evidence for an idle completed session; uncertainty never authorizes a signal."""
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
from contextlib import closing


def owned_unit(value):
    if not isinstance(value, str) or not re.fullmatch(r'ethen-code-[0-9a-f]{32}\.scope', value):
        raise PermissionError('Unknown worker scope identity')
    return value


def scope_status(unit):
    owned_unit(unit)
    result = subprocess.run(['systemctl', '--user', 'show', '-p', 'Id', '-p', 'LoadState',
                             '-p', 'ActiveState', '-p', 'ControlGroup', '--', unit],
                            env={'PATH': '/usr/bin:/bin', 'XDG_RUNTIME_DIR': f'/run/user/{os.getuid()}'},
                            capture_output=True, text=True, check=False, timeout=10)
    values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if result.returncode or values.keys() != {'Id', 'LoadState', 'ActiveState', 'ControlGroup'} or values['Id'] != unit:
        raise PermissionError('Scope state could not be established')
    return values


def require_absent_scope(unit):
    state = scope_status(unit)
    if state['LoadState'] not in {'not-found', 'loaded'} or state['ActiveState'] != 'inactive' or state['ControlGroup']:
        raise PermissionError('Scope is present or ambiguous; refusing idle stop')


def require_active_scope(unit, pid):
    state = scope_status(unit)
    group = state['ControlGroup']
    if state['LoadState'] != 'loaded' or state['ActiveState'] != 'active' or not group.startswith('/') or group == '/':
        raise PermissionError('Active worker scope is unknown')
    membership = Path('/proc', str(pid), 'cgroup').read_text().splitlines()
    if len(membership) != 1 or not membership[0].startswith('0::'):
        raise PermissionError('Worker cgroup identity is ambiguous')
    actual = membership[0][3:]
    if actual != group and not actual.startswith(group + '/'):
        raise PermissionError('Worker is outside its recorded owned scope')


def read_database(path):
    if path.is_symlink() or not path.is_file():
        raise PermissionError('Missing or symlink session evidence')
    return sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)


def require_completed(session):
    from ethen.code.product_workspace import validate_workspace, git_read
    from ethen.code.qualification import AFTER
    validate_workspace(session)
    repo = session / 'project'
    receipt = json.loads((session / 'evidence/receipt.json').read_text())
    with closing(read_database(session / 'evidence/budget.db')) as db:
        row = db.execute("SELECT payload FROM receipts JOIN reservations USING(request) "
                         "WHERE request=? AND state='completed'", ('owned-issue-attempt-1',)).fetchone()
        pending = db.execute("SELECT 1 FROM reservations WHERE state='reserved' LIMIT 1").fetchone()
    if row is None or pending or json.loads(row[0]) != receipt:
        raise PermissionError('Idle stop requires the durable completed receipt')
    if (receipt.get('schema') != 2 or receipt.get('issue') != 'owned-issue'
            or receipt.get('native_agent') is not True or receipt.get('session_recovery') is not True
            or receipt.get('push_merge_deployment') is not False
            or receipt.get('test_exit_codes') != [1, 0] or receipt.get('diff_exit') != 0):
        raise PermissionError('Completion evidence is not qualified')
    if (git_read(repo, 'rev-parse', 'HEAD').strip() != receipt.get('baseline_sha')
            or git_read(repo, 'branch', '--show-current').strip() != receipt.get('branch')
            or git_read(repo, 'diff', '--name-only').splitlines() != receipt.get('changed_files')
            or (repo / 'calc.py').read_text() != AFTER):
        raise PermissionError('Completed workspace differs from its receipt')
    with closing(read_database(session / 'evidence/session.db')) as db:
        history = db.execute("SELECT 1 FROM messages WHERE session_id=? AND role='tool' LIMIT 1",
                             ('owned-issue',)).fetchone()
    if history is None:
        raise PermissionError('Completed session lacks native history')
