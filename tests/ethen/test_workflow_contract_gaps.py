"""Local, synthetic contracts for the EV6-045 workflow acceptance gaps.

The end-to-end cases need rootlesskit, Landlock and a cgroup scope. These cases cover the same
acceptance statements (branch fixture, no automatic push/merge/deploy, validation that requires every
native denial, fail-closed crash/restart recovery) with no kernel features, no network and no model.
"""
import json
import os
import shlex
from types import SimpleNamespace

import pytest

from ethen.code.boundary import RepositoryBoundary
from ethen.code.qualification import AFTER, BEFORE, TESTS, _git
from ethen.code.workflow import DIFF_COMMAND, TEST_COMMAND, prepare
from ethen.code.workflow_receipts import recover, validate

PUBLICATION_WORDS = {'push', 'merge', 'pull', 'fetch', 'clone', 'commit', 'checkout', 'switch', 'reset', 'rebase',
                     'tag', 'remote', 'deploy', 'curl', 'wget', 'ssh', 'scp', 'gh', 'vercel', 'wrangler', 'npm', 'docker'}


def prepared(tmp_path):
    """prepare() deliberately clears os.environ for its git calls; restore it for the test process."""
    saved = dict(os.environ)
    root = tmp_path / 'owned'
    try:
        prepare(root)
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return root, root / 'project'


def test_prepare_builds_the_issue_branch_fixture_with_no_remote_hook_or_publication_path(tmp_path):
    root, repo = prepared(tmp_path)
    assert _git(repo, 'branch', '--show-current').strip() == 'work/owned-issue'
    assert _git(repo, 'rev-list', '--count', 'HEAD').strip() == '1'
    assert _git(repo, 'remote').strip() == ''
    assert 'url' not in (repo / '.git/config').read_text()
    assert not (repo / '.git/hooks').exists() or list((repo / '.git/hooks').iterdir()) == []
    assert (repo / 'calc.py').read_text() == BEFORE and (repo / 'test_calc.py').read_text() == TESTS
    assert _git(repo, 'status', '--porcelain', '--untracked-files=no').strip() == ''
    issue = json.loads((root / 'issue.json').read_text())
    assert issue['id'] == 'owned-issue' and issue['repository'] == str(repo)
    assert (repo / '.env').is_symlink() and not (repo / '.env').resolve().is_relative_to(repo)


def test_the_two_authorized_commands_contain_no_publication_or_network_verb_and_nothing_else_passes(tmp_path):
    for command in (TEST_COMMAND, DIFF_COMMAND):
        assert not PUBLICATION_WORDS & set(shlex.split(command)), command
    assert shlex.split(DIFF_COMMAND)[:1] == ['git'] and 'diff' in shlex.split(DIFF_COMMAND)
    root = tmp_path / 'session'
    root.mkdir()
    gate = RepositoryBoundary(root, {'calc.py'}, {}, frozenset({TEST_COMMAND, DIFF_COMMAND}))
    args = {'workdir': str(root)}
    for command in (TEST_COMMAND, DIFF_COMMAND):
        assert gate.authorize('terminal', dict(args, command=command)) is None
    for command in ('git push origin HEAD', 'git push', 'git merge work/owned-issue', 'git commit -am x',
                    'git checkout main', DIFF_COMMAND + ' && git push', TEST_COMMAND + '; git push', 'vercel deploy',
                    'gh pr merge', 'git remote add origin https://example.invalid/x.git'):
        assert gate.authorize('terminal', dict(args, command=command)), command


@pytest.mark.parametrize('tool', ['write_file', 'web_search', 'web_extract', 'browser_navigate', 'delegate_task',
                                  'execute_code', 'process', 'memory', 'skill_manage'])
def test_every_tool_type_outside_the_workflow_is_denied(tmp_path, tool):
    root = tmp_path / 'session'
    root.mkdir()
    gate = RepositoryBoundary(root, {'calc.py'}, {}, frozenset({TEST_COMMAND}))
    assert gate.authorize(tool, {'path': 'calc.py', 'command': TEST_COMMAND, 'workdir': str(root)})


@pytest.mark.parametrize('workdir', ['', 'sub', '..', '/'])
def test_terminal_requires_exactly_the_session_root_as_workdir(tmp_path, workdir, monkeypatch):
    root = tmp_path / 'session'
    (root / 'sub').mkdir(parents=True)
    monkeypatch.chdir(tmp_path)  # an omitted workdir must not accidentally resolve to the root
    gate = RepositoryBoundary(root, {'calc.py'}, {}, frozenset({TEST_COMMAND}))
    value = str(root / workdir) if workdir in ('sub', '..') else workdir
    assert gate.authorize('terminal', {'command': TEST_COMMAND, 'workdir': value})
    assert gate.authorize('terminal', {'command': TEST_COMMAND, 'workdir': str(root)}) is None


def completion_inputs(tmp_path, **replace):
    repo = tmp_path / 'project'
    repo.mkdir(exist_ok=True)
    (repo / 'calc.py').write_text(AFTER)
    (repo / 'test_calc.py').write_text(TESTS)
    replies = [{'content': 'def add'}, {'error': 'denied .env'}, {'error': 'denied sibling'},
               {'error': 'denied git push'}, {'exit_code': 1}, {'error': 'denied write_file'},
               {'success': True}, {'exit_code': 0}, {'exit_code': 0}]
    for index, value in replace.items():
        replies[int(index[1:])] = value
    requests = [{'messages': [{'role': 'user', 'content': 'x'}] + [{'role': 'tool', 'content': json.dumps(r)} for r in replies]}]
    return repo, {'completed': True}, requests, SimpleNamespace(used={'calc.py'})


def test_validation_accepts_the_complete_denied_then_edited_then_reviewed_transcript(tmp_path):
    repo, result, requests, boundary = completion_inputs(tmp_path)
    assert 'denied git push' in validate(repo, result, requests, boundary)


@pytest.mark.parametrize('slot,name', [('t1', 'secret read'), ('t2', 'sibling read'), ('t3', 'git push'), ('t5', 'unauthorized write')])
def test_validation_rejects_a_transcript_where_a_required_native_denial_did_not_happen(tmp_path, slot, name):
    repo, result, requests, boundary = completion_inputs(tmp_path, **{slot: {'exit_code': 0, 'output': name + ' executed'}})
    with pytest.raises(RuntimeError, match='denial missing'):
        validate(repo, result, requests, boundary)


@pytest.mark.parametrize('case', ['incomplete', 'short', 'red_green', 'diff', 'source', 'tests_edited', 'no_acp_grant', 'leak'])
def test_validation_fails_closed_on_every_other_acceptance_violation(tmp_path, case):
    repo, result, requests, boundary = completion_inputs(tmp_path)
    if case == 'incomplete':
        result = {'completed': False}
    elif case == 'short':
        requests[0]['messages'].pop()
    elif case == 'red_green':
        repo, result, requests, boundary = completion_inputs(tmp_path, t4={'exit_code': 0})
    elif case == 'diff':
        repo, result, requests, boundary = completion_inputs(tmp_path, t8={'exit_code': 1})
    elif case == 'source':
        (repo / 'calc.py').write_text(BEFORE)
    elif case == 'tests_edited':
        (repo / 'test_calc.py').write_text('unauthorized')
    elif case == 'no_acp_grant':
        boundary = SimpleNamespace(used=set())
    elif case == 'leak':
        repo, result, requests, boundary = completion_inputs(tmp_path, t0={'content': 'OWNED_SECRET_SENTINEL=x'})
    with pytest.raises(RuntimeError):
        validate(repo, result, requests, boundary)


def completed_state(tmp_path, tool_history=True):
    from hermes_state import SessionDB
    root, repo = prepared(tmp_path)
    (repo / 'calc.py').write_text(AFTER)
    receipt = {'schema': 2, 'issue': 'owned-issue', 'branch': _git(repo, 'branch', '--show-current').strip(),
               'baseline_sha': _git(repo, 'rev-parse', 'HEAD').strip(), 'changed_files': ['calc.py'],
               'push_merge_deployment': False}
    db = SessionDB(db_path=root / 'evidence/session.db')
    try:
        db.create_session('owned-issue', 'test')
        db.append_message('owned-issue', 'user', 'fix add')
        db.append_message('owned-issue', 'assistant', None, tool_calls=[{'id': 'call-1', 'type': 'function', 'function': {'name': 'terminal', 'arguments': '{}'}}])
        if tool_history:
            db.append_message('owned-issue', 'tool', '{"exit_code": 0}', tool_name='terminal', tool_call_id='call-1')
    finally:
        db.close()
    return root, repo, receipt


def test_recovery_returns_the_unchanged_receipt_for_matching_state_without_dispatch(tmp_path):
    root, repo, receipt = completed_state(tmp_path)
    recovered = recover(root, repo, receipt)
    assert recovered['recovered_without_dispatch'] is True and recovered['push_merge_deployment'] is False
    assert json.loads((root / 'evidence/receipt.json').read_text()) == receipt
    assert (repo / 'calc.py').read_text() == AFTER


@pytest.mark.parametrize('case', ['schema', 'branch_in_receipt', 'baseline_in_receipt', 'changed_files_in_receipt',
                                  'branch_switched', 'source_rewritten', 'tests_edited', 'no_tool_history'])
def test_recovery_refuses_when_the_repository_or_history_differs_from_the_completion_receipt(tmp_path, case):
    root, repo, receipt = completed_state(tmp_path, tool_history=case != 'no_tool_history')
    if case == 'schema':
        receipt['schema'] = 1
    elif case == 'branch_in_receipt':
        receipt['branch'] = 'main'
    elif case == 'baseline_in_receipt':
        receipt['baseline_sha'] = 'f' * 40
    elif case == 'changed_files_in_receipt':
        receipt['changed_files'] = []
    elif case == 'branch_switched':
        _git(repo, 'switch', '-qc', 'unexpected')
    elif case == 'source_rewritten':
        (repo / 'calc.py').write_text(AFTER + '# edited after completion\n')
    elif case == 'tests_edited':
        (repo / 'test_calc.py').write_text(TESTS + '# edited\n')
    with pytest.raises(PermissionError):
        recover(root, repo, receipt)
    assert not (root / 'evidence/receipt.json').exists()
