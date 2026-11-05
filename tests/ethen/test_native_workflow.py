"""Owned Linux end-to-end checks through the real Hermes worker and kernel gates."""
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys

import pytest

from tests.waiting import wait_until

pytestmark = [pytest.mark.platforms('linux'),
              pytest.mark.skipif(os.environ.get('HERMES_RUN_E2E') != '1', reason='owned native opt-in required')]
SOURCE = Path(__file__).resolve().parents[2]


def command(root, mode='success', resume=False):
    return ['rootlesskit', '--net=host', 'unshare', '--net', 'bash', '-c',
            'ip link set lo up; exec "$@"', '_', sys.executable, '-m', 'ethen.code.isolation',
            '--resume' if resume else '--prepare', str(root), mode]


def clean_env(tmp_path):
    home = tmp_path / 'controller-home'
    home.mkdir(exist_ok=True)
    return {'PATH': str(Path(sys.executable).parent) + ':/usr/bin:/bin',
            'HOME': str(home), 'LANG': 'C.UTF-8', 'TZ': 'UTC', 'PYTHONDONTWRITEBYTECODE': '1'}


def counters(root):
    with sqlite3.connect(root / 'evidence/budget.db') as db:
        return db.execute('SELECT request,state,cost,tokens FROM reservations ORDER BY request').fetchall()


def launch(root, env, mode='success', resume=False):
    return subprocess.run(command(root, mode, resume), cwd=SOURCE, env=env,
                          capture_output=True, text=True, timeout=120, check=False)


def test_native_issue_review_and_fresh_process_receipt_recovery(tmp_path):
    root = tmp_path / 'success'
    env = clean_env(tmp_path)
    result = launch(root, env)
    assert result.returncode == 0, result.stderr
    receipt = json.loads((root / 'evidence/receipt.json').read_text())
    assert receipt['native_agent'] and receipt['session_recovery']
    assert receipt['test_exit_codes'] == [1, 0] and receipt['diff_exit'] == 0
    assert receipt['changed_files'] == ['calc.py']
    assert not receipt['push_merge_deployment']
    assert sum(d['denied'] for d in receipt['decisions']) == 4
    before = counters(root)
    source = (root / 'project/calc.py').read_bytes()
    resumed = launch(root, env, resume=True)
    assert resumed.returncode == 0, resumed.stderr
    assert counters(root) == before
    assert (root / 'project/calc.py').read_bytes() == source
    assert json.loads((root / 'evidence/receipt.json').read_text()) == receipt


def test_real_post_edit_crash_is_fenced_on_fresh_process_restart(tmp_path):
    root = tmp_path / 'crash'
    env = clean_env(tmp_path)
    result = launch(root, env, mode='crash')
    assert result.returncode == 97, result.stderr
    assert 'return a + b' in (root / 'project/calc.py').read_text()
    assert not (root / 'evidence/receipt.json').exists()
    before = counters(root)
    assert ('owned-issue-attempt-1', 'reserved', '0', 4096) in before
    resumed = launch(root, env, resume=True)
    assert resumed.returncode != 0
    assert 'Duplicate or ambiguous request' in resumed.stderr
    assert counters(root) == before
    assert 'return a + b' in (root / 'project/calc.py').read_text()


def test_native_cancellation_revokes_grants_and_reaps_terminal_child(tmp_path):
    root = tmp_path / 'cancel'
    with subprocess.Popen(command(root, mode='cancel'), cwd=SOURCE, env=clean_env(tmp_path),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as proc:
        try:
            wait_until(lambda: (root / 'project/child.pid').exists() or proc.poll() is not None, timeout=45)
            assert proc.poll() is None
            child = int((root / 'project/child.pid').read_text())
            worker = int((root / 'evidence/worker.pid').read_text())
            os.kill(worker, signal.SIGTERM)
            stdout, stderr = proc.communicate(timeout=30)
            assert proc.returncode == 0, stdout + stderr
            wait_until(lambda: not Path('/proc', str(child)).exists(), timeout=10)
            receipt = json.loads((root / 'evidence/cancel-receipt.json').read_text())
            assert receipt['cancelled'] and receipt['native_interrupt']
            assert not receipt['workflow_completed']
            assert (root / 'project/calc.py').read_text().endswith('return a - b\n')
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.communicate(timeout=15)
