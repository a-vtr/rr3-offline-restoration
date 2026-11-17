"""Inspect an exported lab IPA before approved installation. Never signs/installs.

Detailed profiles/certificates remain in a new private output directory.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import plistlib
import stat
import subprocess
import zipfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('ipa', type=Path)
    p.add_argument('unsigned_app', type=Path)
    p.add_argument('device_inventory', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    repo = Path(__file__).resolve().parents[1]
    output = a.output.resolve()
    if output.exists() or output.is_relative_to(repo):
        p.error('output must be new and outside repository')
    output.mkdir(mode=0o700)
    with zipfile.ZipFile(a.ipa) as z:
        for e in z.infolist():
            path = PurePosixPath(e.filename)
            if path.is_absolute() or '..' in path.parts or stat.S_ISLNK(e.external_attr >> 16):
                raise ValueError('Unsafe signed archive entry')
        if sum(e.file_size for e in z.infolist()) > 32*1024*1024:
            raise ValueError('Unexpectedly large lab archive')
        assert z.testzip() is None
        z.extractall(output)
    apps = list((output/'Payload').glob('*.app'))
    assert len(apps) == 1
    app = apps[0]
    info = plistlib.loads((app/'Info.plist').read_bytes())
    bundle_id = info['CFBundleIdentifier']
    assert bundle_id.startswith('org.rr3preservation.resourcelab')
    run = lambda args: subprocess.run(args, capture_output=True, check=True, timeout=20).stdout
    run(['codesign','--verify','--deep','--strict','--verbose=2',str(app)])
    decoded = run(['security','cms','-D','-i',str(app/'embedded.mobileprovision')])
    (output/'profile.plist').write_bytes(decoded)
    profile = plistlib.loads(decoded)
    ent_data = run(['codesign','-d','--entitlements',':-',str(app)])
    ent = plistlib.loads(ent_data)
    (output/'entitlements.plist').write_bytes(ent_data)
    now = datetime.now(timezone.utc)
    expiry = profile['ExpirationDate'].replace(tzinfo=timezone.utc)
    creation = profile['CreationDate'].replace(tzinfo=timezone.utc)
    assert creation <= now < expiry
    team = profile['TeamIdentifier'][0]
    assert ent['com.apple.developer.team-identifier'] == team
    expected_id = profile['ApplicationIdentifierPrefix'][0]+'.'+bundle_id
    assert ent['application-identifier'] == expected_id
    assert profile['Entitlements']['application-identifier'] == expected_id
    assert ent.get('get-task-allow') is True
    assert not ent.get('com.apple.security.application-groups')
    inventory = json.loads(a.device_inventory.read_text())['result']['devices']
    devices = [d for d in inventory if d.get('hardwareProperties',{}).get('productType','').startswith('iPad')
               and d.get('connectionProperties',{}).get('transportType') == 'wired']
    assert len(devices) == 1
    udid = devices[0]['hardwareProperties']['udid']
    assert udid in profile['ProvisionedDevices']
    run(['codesign','-d','--extract-certificates='+str(output/'signer-'),str(app)])
    leaf = (output/'signer-0').read_bytes()
    assert leaf in profile['DeveloperCertificates']
    run(['openssl','x509','-inform','DER','-in',str(output/'signer-0'),'-noout','-checkend','0'])
    assert (app/'seed-manifest.json').read_bytes() == (a.unsigned_app/'seed-manifest.json').read_bytes()
    manifest = json.loads((app/'seed-manifest.json').read_text())
    for row in manifest:
        data = (app/'ResourceSeed'/row['path']).read_bytes()
        assert len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256']
    result = {'host_signature_checks_passed':True,'profile_valid_now':True,
              'signer_certificate_in_profile':True,'target_device_in_profile':True,
              'bundle_profile_entitlements_coherent':True,'seed_files':len(manifest),
              'seed_bytes':sum(v['bytes'] for v in manifest),'seed_integrity_passed':True,
              'profile_expiry_utc':expiry.isoformat(),'installed':False,'runtime_tested':False,
              'signed_ipa_sha256':hashlib.sha256(a.ipa.read_bytes()).hexdigest()}
    (output/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='signed_ipa_sha256'}))


if __name__ == '__main__':
    main()
