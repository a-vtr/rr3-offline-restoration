"""Normalize stale embedded signing intent in an isolated UNSIGNED RR3 IPA.

Does not sign: no hashes/CMS/certificates are generated and existing signature
validity is NOT asserted. Impactor must replace the stale signatures. Only the
two app/extension entitlement blobs are normalized; game instructions stay exact.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import struct
import zipfile
from prepare_rr3_identity import MAIN, WIDGET, GROUP, rewrite_records
from trace_resource_startup import Image
from audit_standalone import signing_metadata


def normalize(data, identity):
    image = Image(data)
    command = next(at for cmd, at in image.commands if cmd == 0x1d)
    offset, allocation = struct.unpack_from('<II', data, command + 8)
    old = data[offset:offset + allocation]
    original = signing_metadata(old)
    assert original.get('entitlements'), 'Expected baseline entitlement metadata'
    # Impactor's merge rewrites this ten-character placeholder to the actual
    # profile team. No original/wildcard keychain group is carried forward.
    intent = {'com.apple.security.application-groups':[GROUP],
              'keychain-access-groups':['0000000000.' + identity]}
    xml = plistlib.dumps(intent)
    entitlement = struct.pack('>II', 0xfade7171, len(xml) + 8) + xml
    magic, length, count = struct.unpack_from('>III', old)
    assert magic == 0xfade0cc0 and length <= allocation
    blobs = []
    for i in range(count):
        slot, position = struct.unpack_from('>II', old, 12 + i * 8)
        _, size = struct.unpack_from('>II', old, position)
        assert size >= 8 and position + size <= length
        if slot in (5,7):continue  # Replace XML and drop stale DER entitlements.
        blobs.append((slot, old[position:position + size]))
    blobs.append((5, entitlement))
    cursor = 12 + len(blobs) * 8
    indexes = [];payload = bytearray()
    for slot, blob in blobs:
        indexes.append(struct.pack('>II', slot, cursor));payload.extend(blob);cursor += len(blob)
    rebuilt = struct.pack('>III', 0xfade0cc0, cursor, len(blobs)) + b''.join(indexes) + payload
    if len(rebuilt) > allocation:
        raise ValueError('New metadata does not fit existing signature allocation')
    rebuilt = rebuilt.ljust(allocation,b'\0')
    result = data[:offset] + rebuilt + data[offset + allocation:]
    assert len(result) == len(data)
    assert result[:offset] == data[:offset] and result[offset + allocation:] == data[offset + allocation:]
    parsed = signing_metadata(result[offset:offset + allocation])
    assert parsed['entitlements'] == intent
    assert not any(v['type'] == 7 for v in parsed['slots'])
    text = image.sections[('__TEXT','__text')]
    assert result[text[2]:text[2]+text[1]] == data[text[2]:text[2]+text[1]]
    return result, {'identity':identity,'signature_offset':offset,'signature_allocation':allocation,
        'before_signature_sha256':hashlib.sha256(old).hexdigest(),
        'after_signature_sha256':hashlib.sha256(rebuilt).hexdigest(),
        'intent':intent,'text_unchanged':True,'outside_signature_bytes_unchanged':True,
        'stale_der_removed':True,'cryptographic_signature_valid':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('ipa',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    output=a.output.resolve();repo=Path(__file__).resolve().parents[1]
    if output.exists() or output.is_relative_to(repo):p.error('New private external output required')
    os.umask(0o077);output.mkdir(mode=0o700)
    before=a.ipa.stat()
    components=[('Payload/RealRacing3.app/RealRacing3',MAIN),
        ('Payload/RealRacing3.app/PlugIns/todayWidget.appex/todayWidget',WIDGET)]
    updates={};reports=[]
    with zipfile.ZipFile(a.ipa) as z:
        for name,identity in components:
            info=plistlib.loads(z.read(name.rsplit('/',1)[0]+'/Info.plist'))
            assert info['CFBundleIdentifier']==identity
            data=z.read(name);updated,report=normalize(data,identity)
            # Exact original blob retained privately for a byte-exact reversal.
            at=report['signature_offset'];size=report['signature_allocation']
            (output/(Path(name).name+'-original-signature.bin')).write_bytes(data[at:at+size])
            (output/(Path(name).name+'-entitlements-intent.plist')).write_bytes(plistlib.dumps(report['intent']))
            (output/(Path(name).name+'-normalized.macho')).write_bytes(updated)
            updates[name]=updated;reports.append(report)
        destination=output/'RR3-Restored-three-file-signing-input.ipa'
        with a.ipa.open('rb') as src:rewrite_records(z,src,destination,updates)
        with zipfile.ZipFile(destination) as check:
            assert check.testzip() is None
            for name,data in updates.items():assert check.read(name)==data
            for entry in z.infolist():
                if entry.filename in updates:continue
                other=check.getinfo(entry.filename)
                assert (other.CRC,other.file_size,other.compress_size)==(entry.CRC,entry.file_size,entry.compress_size)
    after=a.ipa.stat()
    assert (before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_size,after.st_mtime_ns,after.st_ctime_ns)
    report={'stage':'corrected UNSIGNED signing input; no signing attempt performed',
        'native_build_id':'4d4488a240d223e1','components':reports,'archive_crc_pass':True,
        'other_entries_unchanged':True,'input_unchanged':True,'install_ready':False}
    (output/'entitlement-normalization.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='components'}))


if __name__=='__main__':main()
