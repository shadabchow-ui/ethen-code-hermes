"""Adversarial native-ACP and path-policy contracts; no tool effects executed."""
import pytest

from acp_adapter.edit_approval import EditProposal
from ethen.code.boundary import RepositoryBoundary


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / 'session-a'
    root.mkdir()
    (root / 'calc.py').write_text('return a - b\n')
    return root


def boundary(root, readable=None):
    return RepositoryBoundary(root, readable or {'calc.py'}, {'calc.py': ('return a - b', 'return a + b')}, frozenset({'python3 -B -m unittest -v test_calc'}))


def proposal(root, **overrides):
    fields = dict(tool_name='patch', path=str(root / 'calc.py'), old_text='return a - b', new_text='return a + b', arguments={})
    fields.update(overrides)
    return EditProposal(**fields)


def test_native_exact_edit_grant_is_consumed_once(workspace):
    gate = boundary(workspace)
    assert gate.authorize('read_file', {'path': str(workspace / 'calc.py')}) is None
    assert gate.approve_edit(proposal(workspace)) is True
    assert gate.approve_edit(proposal(workspace)) is False
    assert gate.authorize('patch', {'path': 'calc.py', 'old_string': 'return a - b', 'new_string': 'return a + b'})


@pytest.mark.parametrize('secret', ['.env', '.env.production', '.git/config', 'private.pem', 'id_rsa', 'id_ed25519'])
def test_secret_read_denied_even_if_accidentally_listed(workspace, secret):
    assert boundary(workspace, {secret}).authorize('read_file', {'path': secret})


def test_cross_session_reads_and_multifile_edits_denied(workspace, tmp_path):
    other = tmp_path / 'session-b'
    other.mkdir()
    (other / 'calc.py').write_text('secret\n')
    gate = boundary(workspace)
    assert gate.authorize('read_file', {'path': str(other / 'calc.py')})
    assert gate.approve_edit(proposal(workspace, paths=(str(workspace / 'calc.py'), str(other / 'calc.py')))) is False


def test_symlink_read_and_edit_escape_are_denied(workspace, tmp_path):
    outside = tmp_path / 'private.py'
    outside.write_text('secret\n')
    (workspace / 'escape.py').symlink_to(outside)
    gate = boundary(workspace, {'escape.py'})
    assert gate.authorize('read_file', {'path': 'escape.py'})
    assert gate.approve_edit(proposal(workspace, path=str(workspace / 'escape.py'))) is False


@pytest.mark.parametrize('command', ['git push origin main', 'git merge other', 'curl https://example.com', 'python3 -B -m unittest -v test_calc; rm calc.py'])
def test_terminal_command_allowlist_is_exact(workspace, command):
    gate = boundary(workspace)
    assert gate.authorize('terminal', {'workdir': str(workspace), 'command': command})


def test_terminal_workdir_resolution_failure_is_a_denial_not_exception(workspace):
    (workspace / 'loop').symlink_to('loop')
    gate = boundary(workspace)
    assert gate.authorize('terminal', {'workdir': str(workspace / 'loop'), 'command': 'git push origin main'})


def test_cancel_revokes_previously_prepared_native_proposal(workspace):
    gate = boundary(workspace)
    pending = proposal(workspace)
    gate.cancel()
    assert gate.approve_edit(pending) is False
    assert gate.authorize('read_file', {'path': 'calc.py'})
    assert gate.authorize('terminal', {'workdir': str(workspace), 'command': 'python3 -B -m unittest -v test_calc'})


def test_unapproved_payload_does_not_consume_valid_grant(workspace):
    gate = boundary(workspace)
    assert gate.approve_edit(proposal(workspace, new_text='malicious payload')) is False
    assert gate.approve_edit(proposal(workspace)) is True
