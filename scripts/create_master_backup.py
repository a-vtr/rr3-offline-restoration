"""Create one new macOS external master, then verify against a private baseline.

Requires explicit owner authorization before invocation. Refuses existing targets,
source drift, symlinks/special files, nested mounts, or shared physical storage.
Never deletes failed backups. Detailed output is private; no network operations.
"""
import argparse
import collections
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
import plistlib

from preservation_baseline import signature, write_json


def disk_info(path):
    result = subprocess.run(['/usr/sbin/diskutil', 'info', '-plist', str(path)],
                            check=True, capture_output=True)
    return plistlib.loads(result.stdout)


def physical_disks(info):
    stores = info.get('APFSPhysicalStores', [])
    if not stores:
        raise ValueError('Cannot establish APFS physical backing')
    return sorted({disk_info(s['APFSPhysicalStore'])['ParentWholeDisk'] for s in stores})


def tree(root):
    files, dirs = {}, {}
    def error(exc):
        raise exc
    device = root.lstat().st_dev
    for base, children, names in os.walk(root, followlinks=False, onerror=error):
        p = Path(base)
        dirs[str(p.relative_to(root))] = p.lstat()
        for name in children + names:
            path = p / name
            s = path.lstat()
            if s.st_dev != device or not (stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode)):
                raise ValueError('Unexpected mount, symbolic link, or special file: ' + str(path))
            if stat.S_ISREG(s.st_mode):
                files[str(path.relative_to(root))] = s
    return files, dirs


class DarwinMetadata:
    """Read-only Darwin APIs; Python on this host lacks os.listxattr."""
    def __init__(self):
        self.lib = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
        self.lib.listxattr.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
        self.lib.listxattr.restype = ctypes.c_ssize_t
        self.lib.getxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
        self.lib.getxattr.restype = ctypes.c_ssize_t
        self.lib.acl_get_file.argtypes = [ctypes.c_char_p, ctypes.c_int]
        self.lib.acl_get_file.restype = ctypes.c_void_p
        self.lib.acl_to_text.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ssize_t)]
        self.lib.acl_to_text.restype = ctypes.c_void_p
        self.lib.acl_free.argtypes = [ctypes.c_void_p]

    def checked(self, value):
        if value < 0:
            raise OSError(ctypes.get_errno(), os.strerror(ctypes.get_errno()))
        if value > 64 * 1024 * 1024:
            raise ValueError('Unexpectedly large metadata')
        return value

    def read(self, path, s):
        encoded = os.fsencode(path)
        size = self.checked(self.lib.listxattr(encoded, None, 0, 1))
        buffer = ctypes.create_string_buffer(size)
        got = self.checked(self.lib.listxattr(encoded, buffer, size, 1))
        attrs = {}
        for name in buffer.raw[:got].split(b'\0'):
            if not name:
                continue
            amount = self.checked(self.lib.getxattr(encoded, name, None, 0, 0, 1))
            value = ctypes.create_string_buffer(amount)
            actual = self.checked(self.lib.getxattr(encoded, name, value, amount, 0, 1))
            attrs[os.fsdecode(name)] = {'bytes': actual, 'sha256': hashlib.sha256(value.raw[:actual]).hexdigest()}
        acl = self.lib.acl_get_file(encoded, 0x100)  # ACL_TYPE_EXTENDED
        text = None
        acl_text = ''
        # Darwin can report ENOENT for an existing object with no extended ACL.
        # Confirm the object still exists; preserve all other errors.
        if not acl and ctypes.get_errno() == errno.ENOENT:
            path.lstat()
        elif not acl:
            raise OSError(ctypes.get_errno(), 'acl_get_file failed')
        try:
            if acl:
                length = ctypes.c_ssize_t()
                text = self.lib.acl_to_text(acl, ctypes.byref(length))
                if not text:
                    raise OSError(ctypes.get_errno(), 'acl_to_text failed')
                acl_text = ctypes.string_at(text, length.value).decode()
        finally:
            if text:
                self.lib.acl_free(text)
            if acl:
                self.lib.acl_free(acl)
        return {'mode': stat.S_IMODE(s.st_mode), 'uid': s.st_uid, 'gid': s.st_gid,
                'mtime_ns': s.st_mtime_ns, 'birthtime_ns': getattr(s, 'st_birthtime_ns', None),
                'flags': s.st_flags, 'xattrs': attrs, 'acl': acl_text}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'baseline', 'volume', 'destination', 'reports', 'source_volume'):
        parser.add_argument(name, type=Path)
    a = parser.parse_args()
    source, baseline, volume, destination, reports, source_volume = [getattr(a, n).absolute() for n in ('source', 'baseline', 'volume', 'destination', 'reports', 'source_volume')]
    repo = Path(__file__).resolve().parents[1]
    if destination.parent != volume or destination.is_symlink() or volume.is_symlink():
        parser.error('destination must be a new immediate child of the actual volume mount')
    for path in (destination, reports):
        if path.resolve().is_relative_to(repo) or path.resolve().is_relative_to(source.resolve()):
            parser.error('private destination/reports must be outside repository and source')
    if os.path.lexists(destination) or os.path.lexists(reports):
        parser.error('destination and report directory must both be new')
    os.umask(0o077)
    reports.mkdir(mode=0o700)
    report = {'started_unix': time.time(), 'status': 'preflight', 'content_verified': False,
              'source': str(source), 'destination': str(destination)}
    output = reports / 'backup-verification.json'
    try:
        expected_rows = [json.loads(line) for line in (baseline / 'inventory.jsonl').read_text().splitlines()]
        expected = {r['path']: r for r in expected_rows}
        expected_dirs = set(json.loads((baseline / 'directories.json').read_text())['structure'])
        if any(r.get('type') != 'file' or not r.get('sha256') or r.get('error') for r in expected_rows):
            raise ValueError('Incomplete source baseline')
        src_files, src_dirs = tree(source)
        if set(src_files) != set(expected) or set(src_dirs) != expected_dirs:
            raise ValueError('Source inventory changed from baseline')
        if any(signature(s) != expected[p]['signature'] for p, s in src_files.items()):
            raise ValueError('Source file metadata changed from baseline; original not rehashed')
        src_disk, dst_disk = disk_info(source_volume), disk_info(volume)
        src_physical, dst_physical = physical_disks(src_disk), physical_disks(dst_disk)
        if set(src_physical) & set(dst_physical) or source.stat().st_dev == volume.stat().st_dev:
            raise ValueError('Source and destination do not have independent physical storage')
        if dst_disk.get('MountPoint') != str(volume) or not dst_disk.get('Writable') or not os.access(volume, os.W_OK):
            raise ValueError('Destination is not a writable mounted volume')
        if dst_disk.get('FilesystemType') != 'apfs':
            raise ValueError('This metadata-preserving workflow requires APFS; reassess other filesystems')
        required = sum(r['size'] for r in expected_rows)
        free = shutil.disk_usage(volume).free
        if free < required + 2 * 1024 ** 3:
            raise ValueError('Insufficient free space including safety margin')
        write_json(reports / 'disk-preflight.json', {'source_volume': src_disk, 'destination_volume': dst_disk,
                   'source_physical_disks': src_physical, 'destination_physical_disks': dst_physical,
                   'available_bytes': free, 'required_content_bytes': required})
        native = DarwinMetadata()
        metadata = {p: native.read(source / p, s) for p, s in (src_dirs | src_files).items()}
        write_json(reports / 'source-metadata.json', metadata)
        print('Preflight passed; source unchanged, storage physically independent. Creating one new master.', flush=True)
        destination.mkdir(mode=0o700)  # Exclusive: no existing contents can be overwritten.
        evidence = destination / 'verification'
        evidence.mkdir(mode=0o700)
        shutil.copy2(baseline / 'inventory.jsonl', evidence / 'source-inventory.jsonl')
        shutil.copy2(baseline / 'directories.json', evidence / 'source-directories.json')
        shutil.copy2(reports / 'source-metadata.json', evidence / 'source-metadata.json')
        shutil.copy2(reports / 'disk-preflight.json', evidence / 'disk-preflight.json')
        data = destination / 'files'
        command = ['/usr/bin/ditto', '-X', '--noclone', '--rsrc', '--extattr', '--qtn', '--acl', str(source), str(data)]
        report.update(status='copying', copy_command=command, source_physical_disks=src_physical,
                      destination_physical_disks=dst_physical, source_files=len(expected), source_bytes=required)
        write_json(output, report)
        env = {k: v for k, v in os.environ.items() if not k.startswith('DITTO')}
        env['DITTOABORT'] = '1'
        with (reports / 'copy.log').open('wb') as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=env)
        report['copy_exit_code'] = result.returncode
        if result.returncode:
            raise RuntimeError('Copy failed; destination retained for review')
        subprocess.run(['/bin/sync'], check=True)
        report['status'] = 'hashing_destination'
        write_json(output, report)
        print('Copy completed. Computing destination SHA-256 for every file.', flush=True)
        subprocess.run([sys.executable, str(repo / 'scripts/preservation_baseline.py'), str(data), str(evidence / 'destination')], check=True)
        actual_rows = [json.loads(line) for line in (evidence / 'destination/inventory.jsonl').read_text().splitlines()]
        actual = {r['path']: r for r in actual_rows}
        hash_summary = json.loads((evidence / 'destination/summary.json').read_text())
        actual_dirs = set(json.loads((evidence / 'destination/directories.json').read_text())['structure'])
        report.update(missing_files=sorted(set(expected) - set(actual)), extra_files=sorted(set(actual) - set(expected)),
                      missing_directories=sorted(expected_dirs - actual_dirs), extra_directories=sorted(actual_dirs - expected_dirs),
                      size_mismatches=[p for p in set(expected) & set(actual) if expected[p]['size'] != actual[p].get('size')],
                      hash_mismatches=[p for p in set(expected) & set(actual) if expected[p]['sha256'] != actual[p].get('sha256')],
                      read_errors=hash_summary['errors'], destination_files=hash_summary['file_count'],
                      destination_bytes=hash_summary['bytes'], destination_hashed=hash_summary['hashed'],
                      ipa_sha256=actual.get('RealRacing3.ipa', {}).get('sha256'))
        dst_files, dst_dirs = tree(data)
        metadata_differences = []
        for p, s in (dst_dirs | dst_files).items():
            if p in metadata:
                new = native.read(data / p, s)
                differences = {k: {'source': v, 'destination': new[k]} for k, v in metadata[p].items() if v != new[k]}
                if differences:
                    metadata_differences.append({'path': p, 'differences': differences})
        write_json(reports / 'metadata-differences.json', metadata_differences)
        report['metadata_difference_objects'] = len(metadata_differences)
        report['metadata_difference_fields'] = dict(collections.Counter(k for r in metadata_differences for k in r['differences']))
        # ctime, inode and device necessarily differ across copies; atime changes on read.
        report['metadata_expected_differences'] = 'device, inode, ctime; access times not compared because reads can update them'
        end_files, end_dirs = tree(source)
        report['source_still_matches_baseline'] = (set(end_files) == set(expected) and set(end_dirs) == expected_dirs
            and all(signature(s) == expected[p]['signature'] for p, s in end_files.items())
            and all(signature(end_dirs[p]) == signature(s) for p, s in src_dirs.items()))
        end_disk = disk_info(volume)
        report['destination_physical_identity_stable'] = (physical_disks(end_disk) == dst_physical and end_disk.get('DeviceIdentifier') == dst_disk.get('DeviceIdentifier'))
        checks = ('missing_files', 'extra_files', 'missing_directories', 'extra_directories', 'size_mismatches', 'hash_mismatches', 'read_errors')
        report['content_verified'] = (not any(report[k] for k in checks) and not hash_summary['nonregular']
            and hash_summary['hashed'] == len(expected) and report['source_still_matches_baseline']
            and report['destination_physical_identity_stable'])
        report['status'] = 'verified' if report['content_verified'] else 'verification_failed'
        report['finished_unix'] = time.time()
        write_json(output, report)
        for name in ('backup-verification.json', 'metadata-differences.json', 'copy.log'):
            shutil.copy2(reports / name, evidence / name)
        subprocess.run(['/bin/sync'], check=True)
        print(json.dumps({k: report[k] for k in ('status', 'content_verified', 'destination_files', 'destination_bytes', 'destination_hashed', 'metadata_difference_objects', 'metadata_difference_fields')}), flush=True)
        return 0 if report['content_verified'] else 1
    except Exception as exc:
        report.update(status='failed', content_verified=False, error=str(exc), finished_unix=time.time())
        write_json(output, report)
        print('Backup stopped; originals and any partial destination retained. See private report.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
