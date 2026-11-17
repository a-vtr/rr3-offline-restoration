"""Synthetic signature/page-hash and Mach-O runpath checks; no game data."""
import hashlib
from pathlib import Path
import plistlib
import struct
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from audit_standalone import signing_metadata, verify_code_pages
from inspect_ipa import macho_header


def directory(content, kind):
    algorithm = 'sha1' if kind == 1 else 'sha256'
    hashes = [hashlib.new(algorithm, content[i:i + 4096]).digest() for i in range(0, len(content), 4096)]
    identifier = b'test.invalid\0'
    offset = 52 + len(identifier)
    size = offset + sum(map(len, hashes))
    header = struct.pack('>9I4B3I', 0xfade0c02, size, 0x20200, 2, offset, 52,
                         0, len(hashes), len(content), len(hashes[0]), kind, 0, 12, 0, 0, 0)
    return header + identifier + b''.join(hashes)


def main():
    content = b'A' * 4096 + b'B' * 4096 + b'C' * 13
    blobs = [directory(content, 1), directory(content, 2)]
    entitlements = plistlib.dumps({'get-task-allow': False})
    blobs.append(struct.pack('>II', 0xfade7171, len(entitlements) + 8) + entitlements)
    start = 12 + 8 * len(blobs)
    indexes = b''
    for slot, blob in zip((0, 0x1000, 5), blobs):
        indexes += struct.pack('>II', slot, start)
        start += len(blob)
    signature = struct.pack('>III', 0xfade0cc0, start, len(blobs)) + indexes + b''.join(blobs)
    metadata = signing_metadata(signature)
    assert len(metadata['code_directories']) == 2
    assert metadata['entitlements']['get-task-allow'] is False
    assert all(d['adhoc_flag'] for d in metadata['code_directories'])
    with tempfile.TemporaryDirectory() as t:
        p = Path(t) / 'fixture.zip'
        with zipfile.ZipFile(p, 'w') as z:
            z.writestr('match', content + b'unsigned trailer')
            z.writestr('changed', content[:4100] + b'X' + content[4101:])
        with zipfile.ZipFile(p) as z:
            assert all(r['status'] == 'match' for r in verify_code_pages(z, 'match', signature))
            changed = verify_code_pages(z, 'changed', signature)
            assert all(r['mismatch_count'] == 1 and r['first_mismatched_pages'] == [1] for r in changed)
    text = b'@executable_path/Frameworks\0'
    command_size = (12 + len(text) + 7) // 8 * 8
    rpath = struct.pack('<III', 0x8000001c, command_size, 12) + text
    rpath = rpath.ljust(command_size, b'\0')
    path = b'@rpath/example.dylib\0'
    load_size = (24 + len(path) + 7) // 8 * 8
    weak = (struct.pack('<6I', 0x80000018, load_size, 24, 0, 0, 0) + path).ljust(load_size, b'\0')
    header = struct.pack('<8I', 0xfeedfacf, 0x100000c, 0, 2, 2, len(rpath) + len(weak), 0, 0)
    parsed = macho_header(header + rpath + weak)
    assert parsed['rpaths'] == ['@executable_path/Frameworks']
    assert parsed['dependency_commands'][0]['linkage'] == 'weak'
    print('PASS: CodeDirectory/entitlements parsing, SHA-1 and SHA-256 page match/mismatch, partial last page, unsigned trailer, Mach-O runpaths')


if __name__ == '__main__':
    main()
