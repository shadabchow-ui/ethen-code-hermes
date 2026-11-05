"""Reproducible source archive from a sealed Git commit; no binary downloads/builds."""
import argparse
import gzip
import io
import json
from pathlib import Path
import subprocess
import tarfile


def build(source: Path, commit: str, output: Path) -> None:
    sha = subprocess.check_output(['git', '-C', str(source), 'rev-parse', commit + '^{commit}'], text=True).strip()
    tree = subprocess.check_output(['git', '-C', str(source), 'rev-parse', sha + '^{tree}'], text=True).strip()
    raw = subprocess.check_output(['git', '-C', str(source), 'archive', '--format=tar', sha])
    with tarfile.open(fileobj=io.BytesIO(raw)) as original, output.open('xb') as destination:
        with gzip.GzipFile(fileobj=destination, mode='wb', filename='', mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w') as package:
                for entry in original:
                    entry.mtime, entry.uid, entry.gid = 0, 0, 0
                    entry.uname = entry.gname = ''
                    entry.pax_headers = {}
                    package.addfile(entry, original.extractfile(entry) if entry.isfile() else None)
                provenance = json.dumps({'sha': sha, 'tree': tree}, sort_keys=True).encode()
                entry = tarfile.TarInfo('ethen-package-source.json')
                entry.size, entry.mode = len(provenance), 0o644
                package.addfile(entry, io.BytesIO(provenance))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    build(Path(__file__).resolve().parents[2], args.commit, args.out)
