"""Create only the owned synthetic repository; never import arbitrary repository code."""
from pathlib import Path
import json
import sys

from ethen.code.workflow import prepare

if __name__ == '__main__':
    root = Path(sys.argv[1])
    if not root.is_absolute() or root.resolve() != root or root.exists() or root.is_symlink():
        raise SystemExit('New absolute owned session required')
    prepare(root)
    from ethen.code.package_inventory import inventory
    (root / 'evidence/git-baseline.json').write_text(json.dumps(inventory(root / 'project/.git')))
