"""Prepare an unsigned, metadata-only RR3 staging IPA. Does not sign/install.

Copies unchanged compressed ZIP records verbatim. Original signature blobs are
retained as baseline evidence, not valid installation authority. Signing must
replace them and satisfy signing-policy.json before any installation.
"""
import argparse
import copy
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import plistlib
import shutil
import struct
import zipfile

MAIN = 'org.rr3preservation.restored'
WIDGET = MAIN + '.widget'
GROUP = 'group.' + MAIN


def rewrite_records(archive, src, destination, updates, removed=(), additions=None):
    """Reuse unchanged compressed records; replace/add only explicitly named entries.

    Small staging archives only (no ZIP64); caller validates paths and input.
    """
    entries = archive.infolist()
    # Preserve raw central entries and update only their local-header offsets.
    central = {}
    src.seek(archive.start_dir)
    for entry in entries:
        header = src.read(46)
        if header[:4] != b'PK\x01\x02':
            raise ValueError('Invalid central directory')
        n, extra, comment = struct.unpack_from('<HHH', header, 28)
        central[entry.filename] = header + src.read(n + extra + comment)
    ordered = sorted(entries, key=lambda e: e.header_offset)
    records = []
    with destination.open('xb') as dst:
        for i, entry in enumerate(ordered):
            if entry.filename in removed:
                continue
            offset = dst.tell()
            if entry.filename in updates:
                mini = io.BytesIO()
                with zipfile.ZipFile(mini, 'w') as z:
                    z.writestr(copy.copy(entry), updates[entry.filename])
                with zipfile.ZipFile(mini) as z:
                    start = z.start_dir
                    item = z.infolist()[0]
                    length = 46 + len(item.filename.encode('utf-8')) + len(item.extra) + len(item.comment)
                data = mini.getvalue()
                dst.write(data[:start])
                cd = bytearray(data[start:start + length])
            else:
                end = ordered[i + 1].header_offset if i + 1 < len(ordered) else archive.start_dir
                src.seek(entry.header_offset)
                remaining = end - entry.header_offset
                while remaining:
                    chunk = src.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError('Unexpected EOF')
                    dst.write(chunk)
                    remaining -= len(chunk)
                cd = bytearray(central[entry.filename])
            if offset >= 0xffffffff:
                raise ValueError('ZIP64 output requires separate handling')
            struct.pack_into('<I', cd, 42, offset)
            records.append(cd)
        for name, data in (additions or {}).items():
            if name in {v.filename for v in entries}:
                raise ValueError('Added entry collides with existing entry')
            offset = dst.tell()
            mini = io.BytesIO()
            with zipfile.ZipFile(mini, 'w', compression=zipfile.ZIP_DEFLATED) as z:
                item = zipfile.ZipInfo(name, date_time=(2026, 11, 17, 0, 0, 0))
                item.compress_type = zipfile.ZIP_DEFLATED
                item.external_attr = (0o100644 << 16)
                if name.endswith('/RR3Initializer'):
                    item.external_attr = (0o100755 << 16)
                z.writestr(item, data)
            with zipfile.ZipFile(mini) as z:
                central_start = z.start_dir
                item = z.infolist()[0]
                length = 46 + len(name.encode('utf-8')) + len(item.extra) + len(item.comment)
            content = mini.getvalue()
            dst.write(content[:central_start])
            cd = bytearray(content[central_start:central_start + length])
            struct.pack_into('<I', cd, 42, offset)
            records.append(cd)
        start = dst.tell()
        for cd in records:
            dst.write(cd)
        length = dst.tell() - start
        dst.write(struct.pack('<4s4H2IH', b'PK\x05\x06', 0, 0, len(records),
                              len(records), length, start, 0))


def prepare(source, output):
    repo = Path(__file__).resolve().parents[1]
    output = output.resolve()
    if output.exists() or output.is_relative_to(repo):
        raise ValueError('Output must be new and outside the repository')
    before = source.stat()
    output.mkdir(mode=0o700)
    report = {'stage': 'metadata only; NOT an integrated or install-ready build',
              'changes': [], 'executable_records_changed': 0}
    with zipfile.ZipFile(source) as archive, source.open('rb') as src:
        entries = archive.infolist()
        names = [v.filename for v in entries]
        if len(set(names)) != len(names) or len(entries) >= 65535:
            raise ValueError('Duplicate entries or ZIP64 requires separate handling')
        for v in entries:
            p = PurePosixPath(v.filename)
            if p.is_absolute() or '..' in p.parts or v.flag_bits & 1:
                raise ValueError('Unsafe/encrypted archive')
            if max(v.file_size, v.compress_size, v.header_offset) >= 0xffffffff:
                raise ValueError('ZIP64 not supported by this small staging tool')
        main_infos = [n for n in names if n.startswith('Payload/')
                      and n.count('/') == 2 and n.endswith('.app/Info.plist')]
        if len(main_infos) != 1:
            raise ValueError('Expected exactly one application')
        main_info = main_infos[0]
        app = main_info.rsplit('/', 1)[0]
        widget_infos = [n for n in names if n.startswith(app + '/PlugIns/')
                        and n.count('/') == 4 and n.endswith('.appex/Info.plist')]
        if len(widget_infos) != 1:
            raise ValueError('Expected preserved single widget')
        updates = {}
        for name, identity, display in [(main_info, MAIN, 'RR3 Restored'),
                                        (widget_infos[0], WIDGET, 'RR3 Restored Widget')]:
            raw = archive.read(name)
            info = plistlib.loads(raw)
            original = dict(info)
            info['CFBundleIdentifier'] = identity
            info['CFBundleDisplayName'] = display
            # Distinct URL registration prevents taking over the installed game.
            if 'CFBundleURLTypes' in info:
                info['CFBundleURLTypes'] = [{'CFBundleURLName': MAIN,
                    'CFBundleURLSchemes': ['rr3-restored-experiment']}]
            updates[name] = plistlib.dumps(info, fmt=plistlib.FMT_BINARY)
            backup = output / ('main-original.plist' if name == main_info else 'widget-original.plist')
            backup.write_bytes(raw)
            report['changes'].append({'entry': name,
                'fields': {k: {'before': original.get(k), 'after': info[k]}
                           for k in info if info[k] != original.get(k)},
                'before_sha256': hashlib.sha256(raw).hexdigest(),
                'after_sha256': hashlib.sha256(updates[name]).hexdigest()})
        removed = [n for n in names if n.endswith('.xcent') or n.endswith('/embedded.mobileprovision')]
        report['removed_stale_signing_metadata'] = removed
        destination = output / 'RR3-Restored-metadata-only-unsigned.ipa'
        rewrite_records(archive, src, destination, updates, removed)
    with zipfile.ZipFile(destination) as z:
        if z.testzip() is not None:
            raise ValueError('Output CRC failure')
        assert plistlib.loads(z.read(main_info))['CFBundleIdentifier'] == MAIN
        assert plistlib.loads(z.read(widget_infos[0]))['CFBundleIdentifier'] == WIDGET
    after = source.stat()
    assert (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (
        after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    report.update(output_bytes=destination.stat().st_size, output_crc_pass=True,
                  input_metadata_unchanged=True, widget_preserved=True)
    policy = {'main_bundle_identifier': MAIN, 'widget_bundle_identifier': WIDGET,
        'display_name': 'RR3 Restored', 'app_groups': [GROUP],
        'keychain_policy': 'Each bundle gets only its profile-authorized own identifier; no wildcard, original group or com.apple.token',
        'team_policy': 'Same newly authorized signing team/certificate for app and widget; never original EA identities',
        'original_signatures_valid': False, 'install_authorized': False,
        'required_post_sign_checks': ['Fresh device identity collision check for final rewritten IDs',
            'Exact profile/code entitlement coherence, device/certificate/expiry checks',
            'Only experimental app group; no original groups or keychain entitlements',
            'Prove dynamic own-container paths; never open original app data',
            'Explicit owner approval before signing and installation'],
        'app_group_provisioning_verified': False, 'actual_container_separation_verified': False}
    (output/'metadata-changes.json').write_text(json.dumps(report, indent=2)+'\n')
    (output/'signing-policy.json').write_text(json.dumps(policy, indent=2)+'\n')
    print(json.dumps(report | {'changes': len(report['changes'])}))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    if shutil.disk_usage(a.output.parent).free < a.source.stat().st_size + 128*1024*1024:
        p.error('Insufficient staging space')
    prepare(a.source, a.output)
