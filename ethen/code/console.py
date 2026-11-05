"""Local synthetic product presentation through the existing native ACP callback."""
import json
from pathlib import Path


def approve(proposal, root: Path) -> bool:
    print('\nEthen Code — exact edit approval', flush=True)
    print(f'{proposal.tool_name}: {proposal.path}\nBEFORE:\n{proposal.old_text}AFTER:\n{proposal.new_text}', flush=True)
    try:
        allowed = input('Approve this exact edit? Type approve: ').strip() == 'approve'
    except EOFError:
        allowed = False
    (root / 'evidence/operator-approval.json').write_text(json.dumps({'allowed': allowed}))
    return allowed


def event(tool_name, result=None, **metadata):
    print(f'\n[{tool_name}] {result}', flush=True)
