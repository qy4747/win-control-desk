"""Read-only, redacted pattern scan of tracked files or reachable Git history.

This is not a complete PII/secret detector and does not visually inspect images.
Default: current tracked files. --history scans HEAD; --refs scopes published refs.
No network, history rewrite, credential changes, or deletion is performed.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools import build_release


def git(root, *args, data=None):
    return subprocess.run(['git', '-C', str(root), *args], input=data,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          check=True, timeout=120).stdout


def classify(data, name=''):
    findings = []
    if name and build_release.is_sensitive_path(Path(name)):
        findings.append('sensitive-filename')
    if build_release.find_path_leak(data):
        findings.append('personal-path')
    if build_release.find_secret_marker(data):
        findings.append('secret-pattern')
    return findings


def audit_working_tree(root=ROOT):
    names = [p.decode('utf-8') for p in git(root, 'ls-files', '-z').split(b'\0') if p]
    findings = []
    for name in names:
        path = root / name
        if not path.is_file() or path.is_symlink():
            findings.append(dict(path=name, kind='missing-or-symlink'))
            continue
        for kind in classify(path.read_bytes(), name):
            findings.append(dict(path=name, kind=kind))
    return dict(scope='tracked-working-tree', scanned=len(names), findings=findings)


def audit_history(root=ROOT, refs=('HEAD',)):
    # Resolve revisions before use: do not accept options in the refs list.
    revisions = [git(root, 'rev-parse', '--verify', '--end-of-options', ref).decode().strip()
                 for ref in refs]
    named = {}
    for line in git(root, 'rev-list', '--objects', *revisions).splitlines():
        oid, _, name = line.partition(b' ')
        named[oid.decode()] = name.decode('utf-8', 'replace')
    types = git(root, 'cat-file', '--batch-check=%(objectname) %(objecttype)',
                data=('\n'.join(named)+'\n').encode()).decode().splitlines()
    objects = [(oid, kind) for oid, kind in (line.split() for line in types)
               if kind in ('blob', 'commit', 'tag')]
    findings = []
    process = subprocess.Popen(['git', '-C', str(root), 'cat-file', '--batch'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    try:
        for oid, kind in objects:
            process.stdin.write((oid+'\n').encode()); process.stdin.flush()
            header = process.stdout.readline().split()
            if len(header) != 3 or header[0].decode() != oid:
                raise RuntimeError('Unexpected Git object header')
            data = process.stdout.read(int(header[2]))
            if process.stdout.read(1) != b'\n':
                raise RuntimeError('Truncated Git object')
            for finding in classify(data, named[oid] if kind == 'blob' else ''):
                findings.append(dict(object=oid, type=kind, path=named[oid] or '(metadata)', kind=finding))
        process.stdin.close()
        process.wait(timeout=10)
        if process.returncode:
            raise RuntimeError('Git object scan failed')
    finally:
        if process.poll() is None:
            process.terminate(); process.wait(timeout=10)
        process.stdout.close(); process.stderr.close()
    return dict(scope='reachable-history', refs=list(refs), revisions=revisions,
                scanned=len(objects), findings=findings)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', action='store_true')
    parser.add_argument('--refs', nargs='+', default=['HEAD'])
    args = parser.parse_args()
    try:
        result = audit_history(refs=args.refs) if args.history else audit_working_tree()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        print('Audit could not complete; no clean result is claimed.', file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 1 if result['findings'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
