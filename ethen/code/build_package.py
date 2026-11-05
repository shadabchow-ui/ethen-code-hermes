"""Reproducible source archive from a sealed Git commit; no binary downloads/builds."""
import argparse
import gzip
import io
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile


def build(source: Path, commit: str, output: Path) -> None:
    sha = subprocess.check_output(['git', '-C', str(source), 'rev-parse', commit + '^{commit}'], text=True, timeout=30).strip()
    tree = subprocess.check_output(['git', '-C', str(source), 'rev-parse', sha + '^{tree}'], text=True, timeout=30).strip()
    raw = subprocess.check_output(['git', '-C', str(source), 'archive', '--format=tar', sha], timeout=120)
    with tarfile.open(fileobj=io.BytesIO(raw)) as original, output.open('xb') as destination:
        with gzip.GzipFile(fileobj=destination, mode='wb', filename='', mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w') as package:
                files = {}
                for entry in original:
                    entry.mtime, entry.uid, entry.gid = 0, 0, 0
                    entry.uname = entry.gname = ''
                    entry.pax_headers = {}
                    data = original.extractfile(entry).read() if entry.isfile() else None
                    files[entry.name.rstrip('/')] = (['file', hashlib.sha256(data).hexdigest()] if entry.isfile()
                                                     else ['link', entry.linkname] if entry.issym() else ['dir'])
                    package.addfile(entry, io.BytesIO(data) if data is not None else None)
                provenance = json.dumps({'sha': sha, 'tree': tree}, sort_keys=True).encode()
                entry = tarfile.TarInfo('ethen-package-source.json')
                entry.size, entry.mode = len(provenance), 0o644
                package.addfile(entry, io.BytesIO(provenance))
                files[entry.name] = ['file', hashlib.sha256(provenance).hexdigest()]
                listing = json.dumps(files, sort_keys=True).encode()
                entry = tarfile.TarInfo('ethen-package-files.json')
                entry.size, entry.mode = len(listing), 0o644
                package.addfile(entry, io.BytesIO(listing))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    build(Path(__file__).resolve().parents[2], args.commit, args.out)
