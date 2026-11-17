"""Build a private unsigned three-file RR3 pre-nib experiment. Never signs/installs.

Requires the identity-separated staging IPA. Originals/full cache are not inputs.
Keeps nibs/game instructions intact and records an exact executable rollback.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import struct
import subprocess
import zipfile
from prepare_rr3_identity import MAIN, WIDGET, rewrite_records
from rr3_macho_gate import patch_main
from trace_resource_startup import Image
from prototype_resource_seed import checked_path


def nib_delegate_wiring(data):
    """Read only the small NIBArchive graph; never decode/execute UIKit objects."""
    if not data.startswith(b'NIBArchive'):
        raise ValueError('Unexpected main nib format')
    h = struct.unpack_from('<10I', data, 10)
    def variable(p):
        n = shift = 0
        for _ in range(5):
            x = data[p];p += 1;n |= (x & 127) << shift
            if x & 128:return n, p
            shift += 7
        raise ValueError('Malformed nib integer')
    keys = [];p = h[5]
    for _ in range(h[4]):
        n,p = variable(p);keys.append(data[p:p+n].decode());p += n
    classes = [];p = h[9]
    for _ in range(h[8]):
        n,p = variable(p);extra,p = variable(p);p += 4*extra
        classes.append(data[p:p+n].rstrip(b'\0').decode());p += n
    objects = [];p = h[3]
    for _ in range(h[2]):
        c,p = variable(p);s,p = variable(p);n,p = variable(p);objects.append((c,s,n))
    values = [];p = h[7]
    for _ in range(h[6]):
        k,p = variable(p);kind = data[p];p += 1
        if kind in (0,1,2,3,6,7,10):
            length = {0:1,1:2,2:4,3:8,6:4,7:8,10:4}[kind]
            value = int.from_bytes(data[p:p+length],'little');p += length
        elif kind in (4,5,9):value = {4:False,5:True,9:None}[kind]
        elif kind == 8:
            length,p = variable(p);value = data[p:p+length];p += length
        else:raise ValueError('Unsupported nib value')
        values.append((keys[k],kind,value))
    def properties(i):
        _,s,n = objects[i];return {k:v for k,_,v in values[s:s+n]}
    def string(i):return properties(i)['NS.bytes'].decode()
    for i,(c,_,_) in enumerate(objects):
        if classes[c] != 'UIRuntimeOutletConnection':continue
        v = properties(i)
        if string(v['UILabel']) != 'delegate':continue
        source = properties(v['UISource']);destination = properties(v['UIDestination'])
        if (string(source['UIProxiedObjectIdentifier']) == 'IBFilesOwner'
                and string(destination['UIClassName']) == 'RealRacingAppDelegate'):
            return True
    raise ValueError('Nib does not wire owner.delegate to original game delegate')


def build(a):
    repo = Path(__file__).resolve().parents[1]
    output = a.output.resolve()
    if output.exists() or output.is_relative_to(repo) or output.is_relative_to(a.seed.resolve()):
        raise ValueError('Output must be a new private directory outside repository/seed')
    os.umask(0o077)
    env = dict(os.environ, DEVELOPER_DIR=str(a.developer_dir))
    def query(*args):
        return subprocess.run(args,env=env,capture_output=True,text=True,check=True,timeout=20).stdout.strip()
    sdk = query('xcrun','--sdk','iphoneos','--show-sdk-path')
    sdk_version = query('xcrun','--sdk','iphoneos','--show-sdk-version')
    compiler = query('xcrun','--sdk','iphoneos','--find','clang++')
    manifest = json.loads(a.sample_report.read_text())['manifest']
    if len(manifest) != 3 or sum(v['bytes'] for v in manifest) > 1024*1024:
        raise ValueError('Only the existing three-file test seed is allowed')
    output.mkdir(mode=0o700)
    sources = [repo/'native/RRResourceRuntime.mm',repo/'native/ios/RR3Bootstrap.mm']
    source_hashes = {str(p.relative_to(repo)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [*sources,repo/'native/RRResourceRuntime.h',Path(__file__).resolve(),
                  repo/'scripts/rr3_macho_gate.py',repo/'scripts/prepare_rr3_identity.py']}
    build_id = hashlib.sha256(json.dumps({'sources':source_hashes,'manifest':manifest,
        'sdk':sdk_version},sort_keys=True).encode()).hexdigest()[:16]
    app = 'Payload/RealRacing3.app'
    with zipfile.ZipFile(a.staging_ipa) as original:
        info = plistlib.loads(original.read(app+'/Info.plist'))
        widget = plistlib.loads(original.read(app+'/PlugIns/todayWidget.appex/Info.plist'))
        assert info['CFBundleIdentifier'] == MAIN and widget['CFBundleIdentifier'] == WIDGET
        assert 'UIApplicationSceneManifest' not in info and 'NSPrincipalClass' not in info
        before_info = dict(info)
        nib = info.pop('NSMainNibFile')
        ipad_nib = info.pop('NSMainNibFile~ipad')
        assert nib == 'MainWindow' and ipad_nib == 'MainWindowiPad_HD'
        for name in (nib, ipad_nib):nib_delegate_wiring(original.read(app+'/'+name+'.nib'))
        info.update(RR3OriginalMainNib=nib,RR3OriginalMainNibIPad=ipad_nib,
                    RR3InitializerMode='three-file-pre-nib-v1',RR3InitializerBuild=build_id)
        # Actual SDK/libc++ rejected the original deployment target. Use the
        # existing lab's supported minimum, not the owner's exact OS version.
        minimum = '15.0'
        info['MinimumOSVersion'] = minimum
        framework = output/'RR3Initializer.framework';framework.mkdir()
        framework_info = {'CFBundleIdentifier':MAIN+'.initializer','CFBundleName':'RR3Initializer',
            'CFBundleExecutable':'RR3Initializer','CFBundlePackageType':'FMWK',
            'CFBundleVersion':'1','CFBundleShortVersionString':'0.1',
            'MinimumOSVersion':minimum,'CFBundleSupportedPlatforms':['iPhoneOS']}
        (framework/'Info.plist').write_bytes(plistlib.dumps(framework_info))
        command = [compiler,'-target','arm64-apple-ios'+minimum,'-isysroot',sdk,
            '-std=c++17','-fobjc-arc','-fblocks','-Wno-deprecated-declarations',
            '-Wall','-Wextra','-Werror','-I',str(repo/'native'),*map(str,sources),
            '-dynamiclib','-framework','Foundation','-framework','UIKit',
            '-Wl,-no_adhoc_codesign','-Wl,-install_name,@rpath/RR3Initializer.framework/RR3Initializer',
            '-Wl,-exported_symbol,_UIApplicationMain','-o',str(framework/'RR3Initializer')]
        result = subprocess.run(command,env=env,capture_output=True,text=True,timeout=120)
        (output/'build.txt').write_text(result.stdout+result.stderr)
        if result.returncode:raise RuntimeError('Compile failed; see private build.txt')
        component = (framework/'RR3Initializer').read_bytes()
        assert not any(cmd == 0x1d for cmd,_ in Image(component).commands)
        main = original.read(app+'/'+info['CFBundleExecutable'])
        patched,patch = patch_main(main)
        (output/'executable-patch.json').write_text(json.dumps(patch,indent=2)+'\n')
        additions = {app+'/Frameworks/RR3Initializer.framework/'+p.name:p.read_bytes()
                     for p in framework.iterdir()}
        additions[app+'/rr3-seed-manifest.json'] = (json.dumps(manifest,indent=2)+'\n').encode()
        for row in manifest:
            data = checked_path(a.seed,row['path']).read_bytes()
            assert len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256']
            additions[app+'/RR3ResourceSeed/'+row['path']] = data
        updates = {app+'/Info.plist':plistlib.dumps(info,fmt=plistlib.FMT_BINARY),
                   app+'/'+info['CFBundleExecutable']:patched}
        destination = output/'RR3-Restored-three-file-unsigned.ipa'
        before = a.staging_ipa.stat()
        with a.staging_ipa.open('rb') as src:
            rewrite_records(original,src,destination,updates,additions=additions)
        with zipfile.ZipFile(destination) as built:
            assert built.testzip() is None
            assert built.read(app+'/MainWindow.nib') == original.read(app+'/MainWindow.nib')
            assert built.read(app+'/MainWindowiPad_HD.nib') == original.read(app+'/MainWindowiPad_HD.nib')
            assert built.read(app+'/PlugIns/todayWidget.appex/Info.plist') == original.read(app+'/PlugIns/todayWidget.appex/Info.plist')
            for entry in original.infolist():
                if entry.filename in updates:continue
                other = built.getinfo(entry.filename)
                assert (entry.CRC,entry.file_size,entry.compress_size)==(other.CRC,other.file_size,other.compress_size)
            for name,data in additions.items():assert built.read(name)==data
    after = a.staging_ipa.stat()
    assert (before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)
    record = {'build_id':build_id,'compiler_exit':0,'sdk':sdk_version,'minimum_ios':minimum,
        'compiler':query(compiler,'--version').splitlines()[0],
        'main_bundle_identifier':MAIN,'widget_bundle_identifier':WIDGET,
        'main_display_name':info['CFBundleDisplayName'],'widget_preserved':True,
        'nib_owner_delegate_wiring_verified':True,'original_nibs_unchanged':True,
        'original_text_instructions_unchanged':True,'executable_rollback_verified':True,
        'original_launch_callback_body_unchanged':True,
        'metadata_before':before_info,'metadata_after':info,'source_sha256':source_hashes,
        'seed_files':len(manifest),'seed_bytes':sum(v['bytes'] for v in manifest),
        'archive_crc_pass':True,'ipa_bytes':destination.stat().st_size,
        'signed':False,'device_tested':False,'runtime_sequence_verified':False,
        'signing_gate':'main/widget/new framework signatures and separate app/keychain groups must be verified after approved signing',
        'test_limit':'Only three samples; offline test must not permit automatic game downloads. This is not a full offline restoration.'}
    (output/'result.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k not in ('metadata_before','metadata_after','source_sha256')}))


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('staging_ipa',type=Path);p.add_argument('seed',type=Path)
    p.add_argument('sample_report',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--developer-dir',type=Path,default=Path('/Applications/Xcode.app/Contents/Developer'))
    build(p.parse_args())
