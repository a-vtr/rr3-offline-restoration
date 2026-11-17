"""Read-only local inventory. Output MUST be private and outside the source/repo.

Uses standard-library streaming SHA-256; resumes hashes only when path, device,
inode, size, mtime and ctime match. This is a baseline, not backup verification.
Symlinks are recorded, never followed. Does not preserve/access extended attrs.
"""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import stat
import time


def signature(s):
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w') as f:
        json.dump(value, f, indent=2)
        f.write('\n')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    repo = Path(__file__).resolve().parents[1]
    if any(output == p or output.is_relative_to(p) for p in (source, repo)):
        parser.error('output must be outside the source and repository')
    os.umask(0o077)
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / 'inventory.jsonl'
    previous = {}
    if manifest.exists():
        for line in manifest.read_text().splitlines():
            row = json.loads(line)
            if row.get('sha256'):
                previous[row['path']] = row
    errors, rows, directories = [], [], []
    extensions = collections.defaultdict(lambda: [0, 0])
    totals = collections.defaultdict(lambda: [0, 0])
    hashes = collections.defaultdict(list)
    started = time.time()
    reused = hashed = 0
    def walk_error(exc):
        errors.append({'path': str(exc.filename), 'error': str(exc)})
    pending = manifest.with_suffix('.jsonl.tmp')
    with pending.open('w') as dest:
        for root, dirs, files in os.walk(source, followlinks=False, onerror=walk_error):
            dirs.sort()
            files.sort()
            directories.append(str(Path(root).relative_to(source)))
            for name in list(dirs):
                if (Path(root) / name).is_symlink():
                    files.append(name)
                    dirs.remove(name)
            for name in files:
                path = Path(root) / name
                relative = str(path.relative_to(source))
                row = {'path': relative}
                try:
                    before = path.lstat()
                    row.update(size=before.st_size, signature=signature(before),
                               mode=stat.S_IMODE(before.st_mode))
                    if not stat.S_ISREG(before.st_mode):
                        row['type'] = 'symlink' if path.is_symlink() else 'special'
                    else:
                        row['type'] = 'file'
                        old = previous.get(relative, {})
                        if old.get('signature') == row['signature']:
                            row['sha256'] = old['sha256']
                            reused += 1
                        else:
                            digest = hashlib.sha256()
                            flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
                            with os.fdopen(os.open(path, flags), 'rb') as f:
                                if signature(os.fstat(f.fileno())) != row['signature']:
                                    raise OSError('file changed before reading')
                                while chunk := f.read(4 * 1024 * 1024):
                                    digest.update(chunk)
                                if signature(os.fstat(f.fileno())) != row['signature']:
                                    raise OSError('file changed during reading')
                            row['sha256'] = digest.hexdigest()
                            hashed += 1
                        if signature(path.lstat()) != row['signature']:
                            raise OSError('path changed during inspection')
                        hashes[row['sha256']].append(relative)
                        ext = path.suffix.lower() or '(none)'
                        extensions[ext][0] += 1
                        extensions[ext][1] += before.st_size
                        for parent in path.relative_to(source).parents:
                            totals[str(parent)][0] += 1
                            totals[str(parent)][1] += before.st_size
                except OSError as exc:
                    row.pop('sha256', None)
                    row['error'] = str(exc)
                    errors.append({'path': relative, 'error': str(exc)})
                rows.append(row)
                dest.write(json.dumps(row) + '\n')
                dest.flush()
    pending.replace(manifest)
    regular = [r for r in rows if r.get('type') == 'file']
    groups = [v for v in hashes.values() if len(v) > 1]
    sizes = {r['path']: r['size'] for r in regular}
    summary = {
        'source': str(source), 'started_unix': started,
        'elapsed_seconds': round(time.time() - started, 2),
        'file_count': len(regular), 'directory_count_including_root': len(directories),
        'bytes': sum(r['size'] for r in regular),
        'hashed': hashed, 'reused_hashes': reused, 'errors': errors,
        'nonregular': [r for r in rows if r.get('type') != 'file'],
        'zero_length': [r['path'] for r in regular if r['size'] == 0],
        'extensions': dict(sorted(extensions.items())),
        'largest_files': sorted(regular, key=lambda r: r['size'], reverse=True)[:30],
        'largest_directories': sorted(totals.items(), key=lambda x: x[1][1], reverse=True)[:40],
        'duplicate_groups': len(groups),
        'duplicate_extra_files': sum(len(g) - 1 for g in groups),
        'duplicate_extra_bytes': sum((len(g) - 1) * sizes[g[0]] for g in groups),
    }
    write_json(output / 'summary.json', summary)
    write_json(output / 'directories.json', {'structure': directories, 'totals': dict(totals)})
    write_json(output / 'duplicates.json', groups)
    print(json.dumps({k: summary[k] for k in ('file_count', 'directory_count_including_root', 'bytes', 'hashed', 'reused_hashes', 'elapsed_seconds', 'duplicate_groups', 'duplicate_extra_files', 'duplicate_extra_bytes')}))
    print('Errors:', len(errors), 'Zero-length files:', len(summary['zero_length']))


if __name__ == '__main__':
    main()
