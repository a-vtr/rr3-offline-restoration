#!/usr/bin/env python3
"""Check the Git index or public working files and identities without printing secrets.

No dependencies; no changes to the index, working tree, or Git configuration.
This heuristic guard cannot establish copyright ownership or detect every secret.
"""
import argparse
import pathlib
import re
import subprocess
import sys

MAX_BYTES = 2 * 1024 * 1024
PRIVATE_DIRS = {
    '.private', 'private', 'backups', 'working-copies', 'extracted', 'builds',
    'diagnostics', 'payload', 'caches', 'vehicles', 'tracks', 'gui_assets',
    'saves', '.aws', '.ssh',
}
PRIVATE_NOTES = {
    'docs/session_state.md', 'docs/phase1_baseline.md', 'docs/phase2_test01.md',
    'docs/standalone_assessment.md', 'docs/resource_initialization.md',
    'docs/offline_packaging_plan.md',
}
PRIVATE_SUFFIXES = {
    '.ipa', '.dylib', '.dat', '.bak', '.p12', '.pfx', '.pem', '.key', '.cer',
    '.mobileprovision', '.provisionprofile', '.keychain', '.keychain-db',
    '.log', '.ips', '.crash',
}
EMAIL = re.compile(rb'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}')
SECRETS = re.compile(
    rb'(?:-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{20,}'
    rb'|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})'
)


def git(*args):
    return subprocess.run(['git', *args], check=True, capture_output=True).stdout


def private_path(name):
    p = pathlib.PurePosixPath(name.lower())
    return (name.lower() in PRIVATE_NOTES
            or any(part in PRIVATE_DIRS or part.endswith(('.app', '.framework')) for part in p.parts)
            or p.suffix in PRIVATE_SUFFIXES
            or (p.name.startswith('.env') and p.name != '.env.example')
            or p.name in {'credentials.json', 'secrets.json', '.ds_store'})


LOCAL_PATH = re.compile(rb'(?:/Us' rb'ers/[^/\s]+/|/pri' rb'vate/(?:tmp|var)/|/var/' rb'folders/)')
DEVICE_ID = re.compile(rb'\b[0-9A-Fa-f]{8}-(?:[0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}\b')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worktree', action='store_true',
                        help='Review non-ignored working files instead of the index; no staging')
    args = parser.parse_args()
    problems = []
    for role in ('AUTHOR', 'COMMITTER'):
        try:
            identity = git('var', f'GIT_{role}_IDENT').decode()
            address = identity.rsplit('<', 1)[1].split('>', 1)[0]
            if not re.fullmatch(r'[A-Za-z0-9+\-]+@users\.noreply\.github\.com', address):
                problems.append(f'{role.lower()} must use an owner-verified GitHub noreply address')
        except (subprocess.CalledProcessError, IndexError):
            problems.append(f'{role.lower()} identity is unavailable; configure verified noreply email')
    if args.worktree:
        paths = git('ls-files', '--cached', '--others', '--exclude-standard', '-z').split(b'\0')
        entries = []
        for raw_path in sorted(set(filter(None, paths))):
            p = pathlib.Path(raw_path.decode())
            if p.is_symlink() or not p.is_file():
                problems.append(f'{ascii(str(p))}: symlink or missing file requires review')
                continue
            entries.append(b'100644 worktree 0\t' + raw_path)
    else:
        entries = git('ls-files', '--stage', '-z').split(b'\0')
    for entry in filter(None, entries):
        metadata, raw_path = entry.split(b'\t', 1)
        mode, oid, stage = metadata.split()
        name = raw_path.decode('utf-8', errors='replace')
        label = ascii(name)  # Escape control characters in filenames.
        if private_path(name):
            problems.append(f'{label}: private/proprietary path')
            continue
        if mode not in (b'100644', b'100755') or stage != b'0':
            problems.append(f'{label}: symlink, submodule, or unresolved index entry requires review')
            continue
        size = pathlib.Path(name).stat().st_size if args.worktree else int(git('cat-file', '-s', oid.decode()))
        if size > MAX_BYTES:
            problems.append(f'{label}: file exceeds 2 MiB review limit')
            continue
        content = pathlib.Path(name).read_bytes() if args.worktree else git('cat-file', 'blob', oid.decode())
        if b'\0' in content:
            problems.append(f'{label}: binary content requires review')
        if LOCAL_PATH.search(content):
            problems.append(f'{label}: personal/local filesystem path requires review (value withheld)')
        if DEVICE_ID.search(content):
            problems.append(f'{label}: UUID requires privacy review (value withheld)')
        if SECRETS.search(content):
            problems.append(f'{label}: possible credential/key detected (value withheld)')
        if any(not e.lower().endswith(b'@users.noreply.github.com') for e in EMAIL.findall(content)):
            problems.append(f'{label}: email address requires privacy review (value withheld)')
    if problems:
        print('Publication guard blocked:\n- ' + '\n- '.join(problems), file=sys.stderr)
        return 1
    scope = 'working files' if args.worktree else 'index'
    print(f'Publication guard passed: {scope} and noreply identity checks only; manual review still required.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
