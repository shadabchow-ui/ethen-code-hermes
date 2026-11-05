"""Exact offline source artifact installation and complete native CLI lifecycle."""
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tarfile

import pytest

from tests.waiting import wait_until

pytestmark = [pytest.mark.platforms('linux'),
              pytest.mark.skipif(os.environ.get('HERMES_RUN_E2E') != '1', reason='owned native opt-in')]


def test_clean_offline_install_native_cli_lifecycle_and_rollback(tmp_path, pytestconfig):
    artifact = Path(pytestconfig.getoption('--ethen-artifact'))
    evidence = Path(pytestconfig.getoption('--ethen-evidence'))
    evidence.mkdir(mode=0o700, parents=True)
    source = tmp_path / 'artifact'
    source.mkdir()
    with tarfile.open(artifact) as archive:
        archive.extractall(source, filter='data')
    prefix = tmp_path / 'installed'
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', HERMES_RUNTIME_DIR=pytestconfig.getoption('--ethen-tools'))
    env.pop('PYTHONPATH', None)
    injected = source / '.env'
    injected.write_text('PRIVATE_SENTINEL=not-to-copy')
    rejected = subprocess.run([sys.executable, '-B', '-m', 'ethen.code.package', 'install',
                               '--prefix', str(prefix), '--python', str(Path(sys._base_executable)),
                               '--cache', pytestconfig.getoption('--ethen-cache')],
                              cwd=source, env=env, check=False, capture_output=True, text=True, timeout=90)
    assert rejected.returncode != 0 and not prefix.exists()
    injected.unlink()
    install = subprocess.run([sys.executable, '-B', '-m', 'ethen.code.package', 'install',
                              '--prefix', str(prefix), '--python', str(Path(sys._base_executable)),
                              '--cache', pytestconfig.getoption('--ethen-cache')],
                             cwd=source, env=env, check=False, capture_output=True, text=True, timeout=180)
    assert install.returncode == 0, install.stdout + install.stderr
    (evidence / 'install.log').write_text(install.stdout + install.stderr)
    shutil.copy2(prefix / 'installation.json', evidence / 'installation.json')
    app = prefix / 'bin/ethen-code'

    def cli(*args, answer=None):
        return subprocess.run([str(app), *args], input=answer, cwd=tmp_path, env=env,
                              check=False, capture_output=True, text=True, timeout=180)

    assert cli('--help').returncode == 0
    success = tmp_path / 'success'
    assert cli('init', '--session', str(success)).returncode == 0
    poison = success / 'project/sitecustomize.py'
    poison.write_text('raise RuntimeError("must never execute")')
    assert cli('run', '--session', str(success), answer='approve\n').returncode == 2
    poison.unlink()
    denied_repo = cli('run', '--session', str(success), '--repo', str(tmp_path))
    assert denied_repo.returncode == 2
    run = cli('run', '--session', str(success), '--repo', str(success / 'project'), answer='approve\n')
    assert run.returncode == 0, run.stdout + run.stderr
    (evidence / 'session.log').write_text(run.stdout + run.stderr)
    assert 'exact edit approval' in run.stdout and 'return a + b' in run.stdout
    assert '[terminal]' in run.stdout and 'exit_code' in run.stdout
    receipt = json.loads((success / 'evidence/receipt.json').read_text())
    assert receipt['test_exit_codes'] == [1, 0] and receipt['diff_exit'] == 0
    assert receipt['native_agent'] and not receipt['push_merge_deployment']
    assert cli('receipt', '--session', str(success)).returncode == 0
    proof_paths = [success / 'evidence' / name for name in ['receipt.json', 'budget.db', 'session.db']]
    before_stop = [path.read_bytes() for path in proof_paths]
    assert cli('stop', '--session', str(success)).returncode == 0
    assert cli('stop', '--session', str(success)).returncode == 0
    assert [path.read_bytes() for path in proof_paths] == before_stop
    resumed = cli('resume', '--session', str(success), answer='')
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    (evidence / 'resume.log').write_text(resumed.stdout + resumed.stderr)
    assert 'exact edit approval' not in resumed.stdout
    before_resumed_stop = [path.read_bytes() for path in proof_paths]
    assert cli('stop', '--session', str(success)).returncode == 0
    assert cli('stop', '--session', str(success)).returncode == 0
    assert [path.read_bytes() for path in proof_paths] == before_resumed_stop
    denied = tmp_path / 'denied'
    assert cli('init', '--session', str(denied)).returncode == 0
    refusal = cli('run', '--session', str(denied), answer='deny\n')
    assert refusal.returncode == 3, refusal.stdout + refusal.stderr
    (evidence / 'denial.log').write_text(refusal.stdout + refusal.stderr)
    assert 'Edit denied' in refusal.stdout
    assert 'return a - b' in (denied / 'project/calc.py').read_text()
    assert not (denied / 'evidence/receipt.json').exists()
    crash = tmp_path / 'crash'
    assert cli('init', '--session', str(crash)).returncode == 0
    assert cli('run', '--session', str(crash), '--scenario', 'crash').returncode == 97
    assert cli('resume', '--session', str(crash), answer='').returncode != 0
    cancel = tmp_path / 'cancel'
    assert cli('init', '--session', str(cancel)).returncode == 0
    with subprocess.Popen([str(app), 'run', '--session', str(cancel), '--scenario', 'cancel'],
                          cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as proc:
        try:
            wait_until(lambda: (cancel / 'project/child.pid').exists() or proc.poll() is not None, timeout=60)
            assert proc.poll() is None
            child = int((cancel / 'project/child.pid').read_text())
            stopped = cli('stop', '--session', str(cancel))
            assert stopped.returncode == 0, stopped.stdout + stopped.stderr
            out, err = proc.communicate(timeout=45)
            assert proc.returncode == 0, out + err
            wait_until(lambda: not Path('/proc', str(child)).exists(), timeout=10)
            assert json.loads((cancel / 'evidence/cancel-receipt.json').read_text())['cancelled']
        finally:
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
                proc.communicate(timeout=45)
    for name, session in [('success', success), ('denied', denied), ('cancel', cancel), ('crash', crash)]:
        shutil.copytree(session / 'evidence', evidence / name)
    unknown = prefix / 'retain-unknown.txt'
    unknown.write_text('must not delete')
    rollback_command = [sys.executable, '-B', '-m', 'ethen.code.package', 'uninstall', '--prefix', str(prefix)]
    refused = subprocess.run(rollback_command, cwd=source, env=env, check=False, capture_output=True, text=True, timeout=90)
    assert refused.returncode != 0 and unknown.read_text() == 'must not delete'
    unknown.unlink()
    rollback = subprocess.run(rollback_command, cwd=source, env=env, check=False, capture_output=True, text=True, timeout=90)
    assert rollback.returncode == 0, rollback.stdout + rollback.stderr
    assert not prefix.exists() and (success / 'evidence/receipt.json').exists()
    (evidence / 'lifecycle.json').write_text(json.dumps({'install': 0, 'start': 0, 'run': 0,
        'denial': 3, 'resume': 0, 'crash': 97, 'stop': 0, 'child_reaped': True,
        'rollback': 0, 'rollback_unknown_file_refused': True, 'session_evidence_preserved': True,
        'idle_stop_before_and_after_resume': [0, 0, 0, 0], 'idle_stop_receipts_unchanged': True}))
