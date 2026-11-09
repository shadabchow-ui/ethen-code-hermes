"""No push/merge/deploy is reachable through ANY entry of the workflow's real command table.

Gap closed (independent review of b3edfe49f1, mutant Y08): the no-auto-push unit evidence only looked
for deny-words among the shlex tokens of the two authorized commands, so an alias hidden in a git `-c`
option (`-c alias.x=push x diff`) defeated it while every non-E2E test stayed green.

These tests read the table the real `workflow.run` hands to the real `RepositoryBoundary` (parsed from
its source, never re-typed here), then check each entry structurally (git global options allowlist,
subcommand, arguments), execute the git entry for real in the real `prepare()` fixture while tracing
every git subcommand that actually runs and watching a local bare "remote", and finally throw argument
injection, shell metacharacters, aliases and non-string commands at the real gate.

Synthetic only: tmp_path repositories and a local bare directory as the "remote"; no network, no model.
"""
import ast
import inspect
import os
import re
import shlex
import subprocess
import sys

import pytest

from ethen.code import workflow
from ethen.code.boundary import RepositoryBoundary
from ethen.code.qualification import AFTER, _git
from ethen.code.workflow import DIFF_COMMAND, TEST_COMMAND, prepare

SHELL_METACHARACTERS = set(';&|<>$`\\(){}*?[]!~#"\'\n\r\t')
ALLOWED_GIT_GLOBAL_CONFIG = {'core.fsmonitor=false', 'core.hooksPath=/dev/null'}
PUBLICATION_SUBSTRINGS = ('push', 'merge', 'deploy', 'remote', 'fetch', 'pull', 'clone', 'http', 'ssh', 'socket',
                          'subprocess', 'urllib', 'curl', 'wget', 'git')


def prepared(tmp_path):
    saved = dict(os.environ)
    root = tmp_path / 'owned'
    try:
        prepare(root)
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return root, root / 'project'


def _literal_or_name(node):
    if isinstance(node, ast.Name):
        return getattr(workflow, node.id)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    raise AssertionError('command table entry is not a module constant or string literal: ' + ast.dump(node))


def real_command_tables():
    """(normal-mode table, cancel-mode table) exactly as workflow.run constructs them."""
    tree = ast.parse(inspect.getsource(workflow.run))
    boundaries = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id == 'RepositoryBoundary']
    assert len(boundaries) == 1 and len(boundaries[0].args) == 4
    table = boundaries[0].args[3]
    assert isinstance(table, ast.Call) and table.func.id == 'frozenset' and isinstance(table.args[0], ast.Set)
    normal = frozenset(_literal_or_name(e) for e in table.args[0].elts)

    assigns = {t.id: n for n in ast.walk(tree) if isinstance(n, ast.Assign)
               for t in n.targets if isinstance(t, ast.Name) and t.id in ('child_code', 'cancel_command')}
    namespace = {'shlex': shlex, 'sys': sys}
    exec(compile(ast.Module([assigns['child_code'], assigns['cancel_command']], []), 'workflow.run', 'exec'), namespace)
    overrides = [n for n in ast.walk(tree) if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Attribute)
                 and n.targets[0].attr == 'commands']
    assert len(overrides) == 1  # the one and only other way the table can change: cancel mode
    value = overrides[0].value
    assert isinstance(value, ast.Call) and value.func.id == 'frozenset' and isinstance(value.args[0], ast.Set)
    assert [e.id for e in value.args[0].elts] == ['cancel_command']
    return normal, frozenset({namespace['cancel_command']}), namespace['child_code']


def git_invocation(command):
    """Parse `git [-c k=v]... SUBCOMMAND args...` strictly; any other global option is a test failure."""
    argv = shlex.split(command)
    assert argv[0] == 'git', command
    config, index = [], 1
    while argv[index].startswith('-'):
        assert argv[index] == '-c', 'unexpected git global option: ' + argv[index]
        config.append(argv[index + 1])
        index += 2
    return config, argv[index], argv[index + 1:]


def test_the_real_command_table_is_exactly_the_two_reviewed_commands_and_the_cancel_sleeper():
    normal, cancel, _ = real_command_tables()
    assert normal == frozenset({TEST_COMMAND, DIFF_COMMAND}) and len(normal) == 2
    assert len(cancel) == 1


def test_the_diff_command_is_one_plain_git_diff_with_only_the_two_hardening_options_and_no_alias():
    assert DIFF_COMMAND == ' '.join(shlex.split(DIFF_COMMAND))  # single spaces, nothing to hide in whitespace
    assert not SHELL_METACHARACTERS & set(DIFF_COMMAND)
    config, subcommand, rest = git_invocation(DIFF_COMMAND)
    assert sorted(config) == sorted(ALLOWED_GIT_GLOBAL_CONFIG)  # no alias.*, pager, external diff, sshCommand...
    assert subcommand == 'diff'
    assert rest == ['--', 'calc.py']
    assert 'alias' not in DIFF_COMMAND.lower()


def test_the_test_command_is_one_plain_unittest_invocation():
    assert TEST_COMMAND == ' '.join(shlex.split(TEST_COMMAND))
    assert not SHELL_METACHARACTERS & set(TEST_COMMAND)
    assert shlex.split(TEST_COMMAND) == ['python3', '-B', '-m', 'unittest', '-v', 'test_calc']


def test_cancel_mode_table_is_the_current_interpreter_running_a_pure_sleeper_with_no_publication_capability():
    _, cancel, child_code = real_command_tables()
    (command,) = cancel
    assert shlex.split(command) == [sys.executable, '-u', '-c', child_code]
    for word in PUBLICATION_SUBSTRINGS:
        assert word not in child_code.lower(), word
    assert re.fullmatch(r'import os,time;from pathlib import Path;Path\(.child\.pid.\)\.write_text\(str\(os\.getpid\(\)\)\);time\.sleep\(60\)', child_code)


def test_no_command_table_entry_other_than_the_cancel_sleeper_mentions_a_publication_verb():
    normal, _, _ = real_command_tables()
    for command in normal:
        argv = shlex.split(command)
        assert not {'push', 'merge', 'pull', 'fetch', 'clone', 'commit', 'checkout', 'switch', 'reset', 'rebase',
                    'tag', 'remote', 'deploy', 'curl', 'wget', 'ssh', 'scp', 'gh'} & set(argv)
        assert not any(token.startswith(('alias.', '!')) or '=push' in token or '=!' in token for token in argv)


def test_prepared_fixture_defines_no_git_alias_and_no_remote_anywhere(tmp_path):
    root, repo = prepared(tmp_path)
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(root / 'home'), 'GIT_CONFIG_NOSYSTEM': '1',
           'GIT_CONFIG_GLOBAL': '/dev/null'}
    listing = subprocess.run(['git', 'config', '--list', '--show-origin'], cwd=repo, env=env,
                             capture_output=True, text=True, check=True).stdout
    assert not re.search(r'(?im)^\S+\s+(alias\.|remote\.|url\.|core\.pager|core\.sshcommand|diff\.external|credential\.)', listing), listing
    assert subprocess.run(['git', 'config', '--get-regexp', r'^alias\.'], cwd=repo, env=env).returncode == 1


def trapped_environment(root, trace):
    return {'PATH': '/usr/bin:/bin', 'HOME': str(root / 'home'), 'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_TEMPLATE_DIR': str(root / 'home/git-template'),
            'GIT_TRACE': str(trace), 'LANG': 'C.UTF-8', 'TZ': 'UTC', 'PYTHONDONTWRITEBYTECODE': '1'}


def test_running_the_real_diff_command_executes_only_git_diff_and_touches_no_remote(tmp_path):
    root, repo = prepared(tmp_path)
    environment = trapped_environment(root, tmp_path / 'git-trace.log')
    bare = tmp_path / 'trap-remote.git'
    untraced = {k: v for k, v in environment.items() if k != 'GIT_TRACE'}  # the trace must show only the command under test
    subprocess.run(['git', 'init', '--bare', '-q', str(bare)], env=untraced, check=True)
    _git(repo, 'remote', 'add', 'origin', str(bare))  # a push, if any alias or injection could reach one, would land here
    (repo / 'calc.py').write_text(AFTER)
    head = _git(repo, 'rev-parse', 'HEAD')
    done = subprocess.run(['/bin/bash', '-c', DIFF_COMMAND], cwd=repo, env=environment, capture_output=True,
                          text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith('diff --git a/calc.py b/calc.py') and '+    return a + b' in done.stdout
    trace = (tmp_path / 'git-trace.log').read_text()
    assert 'built-in: git diff' in trace
    assert 'alias expansion' not in trace and 'push' not in trace.lower() and 'run_command' not in trace
    assert [line for line in trace.splitlines() if 'built-in:' in line and 'built-in: git diff' not in line] == []
    assert subprocess.run(['git', '--git-dir', str(bare), 'for-each-ref'], env=untraced, capture_output=True,
                          text=True, check=True).stdout == ''
    assert _git(repo, 'rev-parse', 'HEAD') == head and _git(repo, 'branch', '--show-current').strip() == 'work/owned-issue'


def test_running_the_real_test_command_passes_on_the_fixed_source_and_runs_no_git(tmp_path):
    root, repo = prepared(tmp_path)
    environment = trapped_environment(root, tmp_path / 'git-trace.log')
    (repo / 'calc.py').write_text(AFTER)
    done = subprocess.run(['/bin/bash', '-c', TEST_COMMAND], cwd=repo, env=environment, capture_output=True,
                          text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    assert 'OK' in done.stderr
    assert not (tmp_path / 'git-trace.log').exists()


def real_boundary(tmp_path):
    root = tmp_path / 'session'
    root.mkdir()
    normal, _, _ = real_command_tables()
    return RepositoryBoundary(root, {'calc.py'}, {}, normal), str(root)


def injected_commands():
    cases = []
    for base in (DIFF_COMMAND, TEST_COMMAND):
        for suffix in (' && git push', ' ; git push origin HEAD', ' | sh', ' $(git push)', ' `git push`', '\ngit push',
                       ' & git push', ' || git push', ' > out', ' < /dev/null', ' extra', ' -- other.py',
                       ' --output=x', ' --ext-diff', ' ', '\t', '\n', ';', ' #', ' -c alias.x=push', ' --exec-path=/tmp',
                       ' -c core.pager=git-push', ' ; vercel deploy', ' && gh pr merge', ' && curl http://x.invalid'):
            cases.append(base + suffix)
        for prefix in (' ', 'env ', 'GIT_CONFIG_COUNT=1 ', 'sudo ', 'time ', '\n', 'FOO=1 ', 'exec ', '!', 'nohup ',
                       'GIT_EXTERNAL_DIFF=git-push '):
            cases.append(prefix + base)
        cases += [base.upper(), base.replace(' ', '  '), base.replace(' ', '\t'), base.replace(' ', '\n'),
                  base.replace('-c ', '--config-env '), base.replace('git ', 'git -c alias.x=push x ', 1),
                  base.replace('diff', 'push'), base.replace('diff', 'diff;'), base.replace('git', '/usr/bin/git'),
                  base.replace('git', 'GIT'), base[:-1], base + base]
    cases += ['git -c alias.x=push x diff -- calc.py', 'git -c alias.diff=push diff -- calc.py',
              'git -c "alias.x=!git push" x', 'git -c core.pager=git-push diff -- calc.py',
              'git -c diff.external=git-push diff -- calc.py', 'git -c core.sshCommand=x diff -- calc.py',
              'git -c remote.origin.pushurl=x diff -- calc.py', 'git push', 'git push origin HEAD',
              'git merge work/owned-issue', 'git remote add origin https://example.invalid/x.git', 'sh -c "git push"',
              'bash -c "git push origin HEAD"', 'python3 -c "import subprocess"', '']
    return [c for c in dict.fromkeys(cases) if c not in (DIFF_COMMAND, TEST_COMMAND)]


@pytest.mark.parametrize('command', injected_commands())
def test_every_injection_alias_and_metacharacter_variant_is_denied_by_the_real_gate(tmp_path, command):
    gate, root = real_boundary(tmp_path)
    assert gate.authorize('terminal', {'command': command, 'workdir': root}), repr(command)


def test_only_the_two_reviewed_commands_pass_the_real_gate_and_only_in_the_session_root(tmp_path):
    gate, root = real_boundary(tmp_path)
    for command in (DIFF_COMMAND, TEST_COMMAND):
        assert gate.authorize('terminal', {'command': command, 'workdir': root}) is None
        assert gate.authorize('terminal', {'command': command, 'workdir': root + '/..'})
        assert gate.authorize('terminal', {'command': command, 'workdir': '/'})
        assert gate.authorize('terminal', {'command': command})


@pytest.mark.parametrize('command', [None, [], ['git', 'push'], ['git', '-c', 'alias.x=push', 'x'], 5, b'git push',
                                     {'git': 'push'}, True, 0.5])
def test_non_string_command_arguments_are_denied_not_crashed_through(tmp_path, command):
    gate, root = real_boundary(tmp_path)
    assert gate.authorize('terminal', {'command': command, 'workdir': root})


@pytest.mark.parametrize('tool', ['Terminal', 'terminal ', ' terminal', 'TERMINAL', 'bash', 'shell', 'run_command',
                                  'execute_code', 'process', 'delegate_task', 'git', 'git_push', 'deploy', ''])
def test_lookalike_or_other_command_running_tools_never_reach_the_command_table(tmp_path, tool):
    gate, root = real_boundary(tmp_path)
    assert gate.authorize(tool, {'command': DIFF_COMMAND, 'workdir': root, 'path': 'calc.py'})
