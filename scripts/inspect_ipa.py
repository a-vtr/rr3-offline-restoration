"""Inspect ZIP entries and selected IPA metadata without extraction/execution.

Writes sensitive details only to the explicitly supplied private output directory.
CRC checks decompress each member in memory in bounded chunks; no files extracted.
"""
import argparse
import collections
import json
from pathlib import Path, PurePosixPath
import plistlib
import struct
import time
import zipfile

from preservation_baseline import signature, write_json


def macho_header(data):
    result = {'magic': data[:4].hex()}
    if data[:4] == b'\xca\xfe\xba\xbe':
        count = struct.unpack_from('>I', data, 4)[0]
        result['fat_architectures'] = [dict(zip(('cpu', 'subtype', 'offset', 'size', 'align'), struct.unpack_from('>IIIII', data, 8 + 20 * i))) for i in range(min(count, 32))]
        return result
    formats = {b'\xcf\xfa\xed\xfe': ('<', 32), b'\xce\xfa\xed\xfe': ('<', 28),
               b'\xfe\xed\xfa\xcf': ('>', 32), b'\xfe\xed\xfa\xce': ('>', 28)}
    if data[:4] not in formats:
        return result
    endian, offset = formats[data[:4]]
    cpu, subtype, kind, count, size, flags = struct.unpack_from(endian + '6I', data, 4)
    result.update(cpu=cpu, cpu_subtype=subtype, file_type=kind, load_commands=count,
                  commands_bytes=size, header_bytes=offset, flags=flags)
    result['architecture'] = {0x100000c: 'arm64', 12: 'arm', 0x1000007: 'x86_64'}.get(cpu, str(cpu))
    result['dependencies'] = []
    result['dependency_commands'] = []
    result['rpaths'] = []
    for _ in range(count):
        if offset + 8 > len(data):
            result['truncated_commands'] = True
            break
        cmd, length = struct.unpack_from(endian + 'II', data, offset)
        if length < 8 or offset + length > len(data):
            result['truncated_commands'] = True
            break
        block = data[offset:offset + length]
        if cmd in (0x21, 0x2c):
            off, amount, cryptid = struct.unpack_from(endian + 'III', block, 8)
            result['encryption'] = {'offset': off, 'size': amount, 'cryptid': cryptid}
        if cmd == 0x1d:
            off, amount = struct.unpack_from(endian + 'II', block, 8)
            result['code_signature'] = {'offset': off, 'size': amount}
        if cmd in (0xc, 0x80000018, 0x8000001f, 0x80000023):
            pos = struct.unpack_from(endian + 'I', block, 8)[0]
            dependency = block[pos:].split(b'\0')[0].decode(errors='replace')
            result['dependencies'].append(dependency)
            result['dependency_commands'].append({'path': dependency, 'command': cmd,
                'linkage': {0xc: 'required', 0x80000018: 'weak', 0x8000001f: 'reexport', 0x80000023: 'upward'}[cmd]})
        if cmd == 0x8000001c:
            pos = struct.unpack_from(endian + 'I', block, 8)[0]
            result['rpaths'].append(block[pos:].split(b'\0')[0].decode(errors='replace'))
        if cmd in (0x25, 0x24, 0x2f, 0x30):
            version, sdk = struct.unpack_from(endian + 'II', block, 8)
            result['minimum_version_command'] = {'command': cmd, 'version': version, 'sdk': sdk}
        if cmd == 0x32:
            platform, version, sdk = struct.unpack_from(endian + 'III', block, 8)
            result['build_version'] = {'platform': platform, 'version': version, 'sdk': sdk}
        offset += length
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('ipa', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    ipa, out = a.ipa.resolve(), a.output.resolve()
    repo = Path(__file__).resolve().parents[1]
    if out.is_relative_to(ipa.parent) or out.is_relative_to(repo):
        p.error('output must be outside the source and repository')
    if not out.is_dir():
        p.error('create a private output directory first')
    report = out / 'ipa-inspection.json'
    before = signature(ipa.stat())
    if report.exists():
        old = json.loads(report.read_text())
        if old.get('source_signature') == before and old.get('inspection_complete'):
            print('Reusing completed inspection for unchanged IPA.')
            return
    r = {'source_signature': before, 'started_unix': time.time()}
    with zipfile.ZipFile(ipa) as z:
        entries = z.infolist()
        names = [e.filename for e in entries]
        r.update(entry_count=len(entries), uncompressed_bytes=sum(e.file_size for e in entries),
                 duplicate_names=[n for n, c in collections.Counter(names).items() if c > 1],
                 unsafe_names=[n for n in names if PurePosixPath(n).is_absolute() or '..' in PurePosixPath(n).parts])
        write_json(out / 'ipa-entries.json', [{'path': e.filename, 'bytes': e.file_size, 'compressed_bytes': e.compress_size, 'crc32': f'{e.CRC:08x}'} for e in entries])
        r['crc_errors'] = []
        r['crc_checked'] = 0
        for e in entries:
            try:
                with z.open(e) as f:
                    while f.read(4 * 1024 * 1024):
                        pass
                r['crc_checked'] += 1
            except (OSError, RuntimeError, zipfile.BadZipFile, NotImplementedError) as exc:
                r['crc_errors'].append({'path': e.filename, 'error': str(exc)})
        apps = sorted({n.split('/')[1] for n in names if n.startswith('Payload/') and len(n.split('/')) > 2 and n.split('/')[1].endswith('.app')})
        r['payload_apps'] = apps
        r['applications'] = []
        for app in apps:
            prefix = f'Payload/{app}/'
            info_entry = z.getinfo(prefix + 'Info.plist')
            if info_entry.file_size > 4 * 1024 * 1024:
                raise ValueError('Unexpectedly large Info.plist')
            info = plistlib.loads(z.read(info_entry))
            fields = ('CFBundleIdentifier', 'CFBundleShortVersionString', 'CFBundleVersion',
                      'CFBundleExecutable', 'MinimumOSVersion', 'DTPlatformVersion',
                      'DTSDKName', 'DTXcode', 'UIDeviceFamily', 'UIRequiredDeviceCapabilities')
            aresult = {'info': {k: info[k] for k in fields if k in info}}
            exe = prefix + info['CFBundleExecutable']
            with z.open(exe) as f:
                aresult['macho'] = macho_header(f.read(1024 * 1024))
            aresult['executable_bytes'] = z.getinfo(exe).file_size
            aresult['frameworks'] = sorted({n[len(prefix + 'Frameworks/'):].split('/')[0] for n in names if n.startswith(prefix + 'Frameworks/')})
            aresult['signing_entries'] = [n for n in names if n.startswith(prefix) and ('_CodeSignature/' in n or n.endswith('.mobileprovision') or n.endswith('.xcent'))]
            aresult['metadata_candidates'] = [n for n in names if n.startswith(prefix) and any(t in n.lower().split('/')[-1] for t in ('manifest', 'asset_list', 'version', 'catalog', 'config'))]
            r['applications'].append(aresult)
    r['source_unchanged'] = signature(ipa.stat()) == before
    r['elapsed_seconds'] = round(time.time() - r['started_unix'], 2)
    r['inspection_complete'] = True
    write_json(report, r)
    print(json.dumps({k: r[k] for k in ('entry_count', 'uncompressed_bytes', 'crc_checked', 'source_unchanged', 'elapsed_seconds')}))
    print('CRC errors:', len(r['crc_errors']), 'Payload applications:', len(r['payload_apps']))
    for app in r['applications']:
        print(json.dumps(app['info']))
        print('Architecture:', app['macho'].get('architecture'), 'Framework count:', len(app['frameworks']))


if __name__ == '__main__':
    main()
