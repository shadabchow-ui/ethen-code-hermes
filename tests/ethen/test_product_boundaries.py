"""Independent adversarial packaging, workspace and process ownership contracts."""
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ethen.code import package, product_processes
from ethen.code.launcher import selected
from ethen.code.package_inventory import inventory, uninstall

pytestmark = pytest.mark.platforms('linux')


@pytest.fixture
def artifact_source(tmp_path):
    source = tmp_path / 'sealed-source'
    source.mkdir()
    (source / 'payload.py').write_text('OWNED_PAYLOAD = True\n')
    (source / 'ethen-package-source.json').write_text(json.dumps({'sha': 'owned-source', 'tree': 'owned-tree'}))
    (source / 'ethen-package-files.json').write_text(json.dumps(inventory(source, {'ethen-package-files.json'})))
    return source


def denied_assemble(*args, **kwargs):
    raise AssertionError('Rejected input reached installation assembly')


@pytest.mark.parametrize('kind', ['ancestor-symlink', 'prefix-symlink', 'noncanonical-parent'])
def test_unsafe_install_prefix_rejected_before_creation(tmp_path, artifact_source, monkeypatch, kind):
    real = tmp_path / 'real'
    real.mkdir()
    if kind == 'ancestor-symlink':
        alias = tmp_path / 'alias'
        alias.symlink_to(real, target_is_directory=True)
        prefix = alias / 'install'
    elif kind == 'prefix-symlink':
        prefix = tmp_path / 'prefix'
        prefix.symlink_to(real / 'install')
    else:
        prefix = real / '..' / 'install'
    monkeypatch.setattr(package, 'assemble', denied_assemble)
    with pytest.raises(ValueError):
        package.install(artifact_source, prefix, Path(sys.executable), tmp_path / 'cache')
    assert not (real / 'install').exists()
    assert not (tmp_path / 'install').exists()


@pytest.mark.parametrize('mutation', ['extra-secret', 'changed-payload', 'external-symlink'])
def test_unsealed_source_never_reaches_assembly(tmp_path, artifact_source, monkeypatch, mutation):
    if mutation == 'extra-secret':
        (artifact_source / '.env').write_text('OWNED_NONSECRET_SENTINEL=must-not-copy\n')
    elif mutation == 'changed-payload':
        (artifact_source / 'payload.py').write_text('OWNED_PAYLOAD = False\n')
    else:
        outside = tmp_path / 'outside.txt'
        outside.write_text('must-not-copy\n')
        (artifact_source / 'external.txt').symlink_to(outside)
        # Even a matching manifest does not authorize an escaping symlink.
        (artifact_source / 'ethen-package-files.json').write_text(json.dumps(inventory(artifact_source, {'ethen-package-files.json'})))
    prefix = tmp_path / 'install'
    monkeypatch.setattr(package, 'assemble', denied_assemble)
    with pytest.raises(PermissionError):
        package.install(artifact_source, prefix, Path(sys.executable), tmp_path / 'cache')
    assert not prefix.exists()


@pytest.mark.parametrize('unknown_file', [False, True])
def test_failed_install_is_conservatively_rollbackable(tmp_path, artifact_source, monkeypatch, unknown_file):
    prefix = tmp_path / 'install'

    def fail_after_owned_prefix(source, target, python, cache):
        assert target == prefix and target.is_dir()
        assert json.loads((target / 'installation.json').read_text())['state'] == 'INSTALLING'
        (target / 'partial-runtime').mkdir()
        (target / 'partial-runtime/owned.txt').write_text('preserved failure payload\n')
        raise RuntimeError('owned offline assembly failure')

    monkeypatch.setattr(package, 'assemble', fail_after_owned_prefix)
    with pytest.raises(RuntimeError, match='owned offline assembly failure'):
        package.install(artifact_source, prefix, Path(sys.executable), tmp_path / 'cache')
    assert json.loads((prefix / 'installation.json').read_text())['state'] == 'FAILED'
    assert (prefix / 'installed-files.json').is_file()
    if unknown_file:
        unknown = prefix / 'user-data.txt'
        unknown.write_text('must not delete\n')
        with pytest.raises(PermissionError):
            uninstall(prefix)
        assert unknown.read_text() == 'must not delete\n'
        assert (prefix / 'partial-runtime/owned.txt').read_text() == 'preserved failure payload\n'
        unknown.unlink()
    uninstall(prefix)
    assert not prefix.exists()
    assert (artifact_source / 'payload.py').is_file()


@pytest.fixture
def owned_session(tmp_path):
    session = tmp_path / 'owned-session'
    result = subprocess.run([sys.executable, '-B', '-m', 'ethen.code.product_prepare', str(session)],
                            capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert selected(session, session / 'project') == session / 'project'
    return session


@pytest.mark.parametrize('filename', ['sitecustomize.py', 'usercustomize.py', 'credentials.txt'])
def test_unexpected_fixture_input_is_denied_before_launch(owned_session, filename):
    path = owned_session / 'project' / filename
    path.write_text('OWNED_UNEXPECTED_INPUT = True\n')
    with pytest.raises(PermissionError, match='Unexpected workspace files'):
        selected(owned_session, owned_session / 'project')
    assert path.read_text() == 'OWNED_UNEXPECTED_INPUT = True\n'


def test_changed_git_metadata_is_denied_before_launch(owned_session):
    config = owned_session / 'project/.git/config'
    with config.open('a') as output:
        output.write('\n[remote "unapproved"]\n\turl = https://example.invalid/owned\n')
    with pytest.raises(PermissionError, match='Git metadata changed'):
        selected(owned_session, owned_session / 'project')


def test_cross_session_identity_denied_before_pidfd_open(tmp_path, monkeypatch):
    session = tmp_path / 'session-a'
    evidence = session / 'evidence'
    evidence.mkdir(parents=True)
    unit = 'ethen-code-' + 'a' * 32 + '.scope'
    (evidence / 'controller-unit.json').write_text(json.dumps({'session': str(session), 'unit': unit}))
    (evidence / 'worker-identity.json').write_text(json.dumps({'session': str(tmp_path / 'session-b'),
                                                            'unit': unit, 'pid': 999999, 'start': 'owned'}))

    def forbidden_pidfd(_):
        raise AssertionError('Cross-session record reached process signaling')

    monkeypatch.setattr(product_processes.os, 'pidfd_open', forbidden_pidfd)
    with pytest.raises(PermissionError, match='another session'):
        product_processes.stop(session)


def test_stale_early_identity_uses_bounded_owned_scope_fallback(tmp_path, monkeypatch):
    unit = 'ethen-code-' + 'b' * 32 + '.scope'
    signals = []
    waits = []

    def stale_stop(_):
        raise ProcessLookupError('owned stale worker identity')

    def wait(*, timeout):
        waits.append(timeout)
        if len(waits) == 1:
            raise subprocess.TimeoutExpired('owned launcher', timeout)
        return 0

    monkeypatch.setattr(product_processes, 'stop', stale_stop)
    monkeypatch.setattr(product_processes, 'kill_scope', lambda target, sig: signals.append((target, sig)))
    product_processes.cancel_owned(tmp_path / 'session', SimpleNamespace(wait=wait, kill=lambda: None), unit)
    assert signals == [(unit, 'SIGTERM'), (unit, 'SIGKILL')]
    assert waits == [30, 15]


def test_failed_scope_kill_does_not_wait_without_bound(tmp_path, monkeypatch):
    def missing_record(_):
        raise FileNotFoundError('owned no worker record')

    waits = []

    def never_exits(*, timeout):
        waits.append(timeout)
        raise subprocess.TimeoutExpired('owned unresponsive launcher', timeout)

    monkeypatch.setattr(product_processes, 'stop', missing_record)
    monkeypatch.setattr(product_processes, 'kill_scope', lambda *args: subprocess.CompletedProcess([], 1))
    with pytest.raises(subprocess.TimeoutExpired):
        product_processes.cancel_owned(tmp_path / 'session', SimpleNamespace(wait=never_exits, kill=lambda: None), 'ethen-code-' + 'c' * 32 + '.scope')
    assert waits == [30, 15]


def test_launch_cleanup_failure_never_waits_without_timeout(tmp_path, monkeypatch):
    waits = []

    class OwnedProcess:
        def __init__(self, *args, **kwargs):
            self.pid = 999999
            self.returncode = None

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            # Popen's context manager waits for its child when leaving the block.
            self.wait()

        def wait(self, timeout=None):
            waits.append(timeout)
            assert timeout is not None, 'Cancellation entered an unbounded process wait'
            raise subprocess.TimeoutExpired('owned unresponsive launcher', timeout)

        def kill(self):
            return None

        def terminate(self):
            return None

        def poll(self):
            return self.returncode

    def missing_worker(_):
        raise FileNotFoundError('owned no ready worker')

    monkeypatch.setattr(product_processes.subprocess, 'Popen', OwnedProcess)
    monkeypatch.setattr(product_processes, 'stop', missing_worker)
    monkeypatch.setattr(product_processes, 'kill_scope', lambda *args: subprocess.CompletedProcess([], 1))
    with pytest.raises((subprocess.TimeoutExpired, RuntimeError)):
        product_processes.launch(tmp_path / 'session', 'interactive', 'ethen-code-' + 'd' * 32 + '.scope')
    assert waits and all(timeout is not None for timeout in waits)


def test_changed_staged_content_is_denied_before_launch(owned_session):
    repo = owned_session / 'project'
    # An index-only removal preserves the fixture and every loose Git object.
    subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(repo),
                    'update-index', '--force-remove', 'calc.py'], check=True,
                   capture_output=True, timeout=10)
    assert (repo / 'calc.py').is_file()
    with pytest.raises(PermissionError, match='Git index staged content changed'):
        selected(owned_session, repo)


def test_symlink_index_is_denied_before_launch(owned_session):
    index = owned_session / 'project/.git/index'
    saved = owned_session / 'owned-index-copy'
    saved.write_bytes(index.read_bytes())
    index.unlink()
    index.symlink_to(saved)
    with pytest.raises(PermissionError, match='Git index staged content changed'):
        selected(owned_session, owned_session / 'project')
