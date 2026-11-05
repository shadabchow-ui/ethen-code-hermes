"""Validation of native completion and durable, non-redispatching recovery."""
import json

from ethen.code.qualification import AFTER, TESTS, _git


def recover(root, repo, cached):
    from hermes_state import SessionDB
    if (cached.get('schema') != 2 or _git(repo, 'branch', '--show-current').strip() != cached['branch']
            or _git(repo, 'rev-parse', 'HEAD').strip() != cached['baseline_sha']
            or _git(repo, 'diff', '--name-only').splitlines() != cached['changed_files']):
        raise PermissionError('Recovered repository state differs from receipt')
    if (repo / 'calc.py').read_text() != AFTER or (repo / 'test_calc.py').read_text() != TESTS:
        raise PermissionError('Recovered source differs from completion receipt')
    recovered = SessionDB(db_path=root / 'evidence/session.db')
    try:
        history, _ = recovered.get_resume_conversations('owned-issue')
        if not any(m.get('role') == 'tool' for m in history):
            raise PermissionError('Recovery lacks native tool history')
    finally:
        recovered.close()
    (root / 'evidence/receipt.json').write_text(json.dumps(cached, indent=2))
    return dict(cached, recovered_without_dispatch=True)


def validate(repo, result, requests, boundary):
    tools = [m for m in requests[-1]['messages'] if m.get('role') == 'tool']
    parsed = [json.JSONDecoder().raw_decode(m['content'])[0] for m in tools]
    if not result.get('completed') or len(parsed) != 9:
        raise RuntimeError('Incomplete native workflow')
    if not all(parsed[i].get('error') for i in (1, 2, 3, 5)):
        raise RuntimeError('Native policy denial missing')
    if [parsed[i].get('exit_code') for i in (4, 7, 8)] != [1, 0, 0]:
        raise RuntimeError('Test or diff exit code incorrect')
    if ((repo / 'calc.py').read_text() != AFTER or (repo / 'test_calc.py').read_text() != TESTS
            or boundary.used != {'calc.py'}):
        raise RuntimeError('Unexpected source changes or missing native ACP approval')
    transcript = json.dumps(requests, sort_keys=True)
    if 'OWNED_SECRET_SENTINEL=' in transcript or 'OWNED_OTHER_SESSION_SENTINEL' in transcript:
        raise RuntimeError('Confidential fixture reached model context')
    return transcript
