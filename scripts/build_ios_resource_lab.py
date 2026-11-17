"""Compile an unsigned ARM64 UIKit lab using an official installed iPhoneOS SDK.

No signing, installation, account operation or RR3 executable modification.
Only the existing small sample seed is bundled; outputs must remain private.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import zipfile
from prototype_resource_seed import checked_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('seed', type=Path)
    parser.add_argument('sample_report', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--developer-dir', type=Path)
    parser.add_argument('--min-ios', default='15.0')
    a = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    seed, output = a.seed.resolve(), a.output.resolve()
    if output.exists() or output.is_relative_to(repo) or output.is_relative_to(seed) or seed.is_relative_to(output):
        parser.error('output must be new, private, outside repository and seed')
    env = os.environ.copy()
    if a.developer_dir:
        env['DEVELOPER_DIR'] = str(a.developer_dir.resolve())
    def query(*args):
        return subprocess.run(args, env=env, capture_output=True, text=True,
                              check=True, timeout=15).stdout.strip()
    # Fail before writing build output if the actual target SDK is unavailable.
    try:
        sdk = Path(query('xcrun', '--sdk', 'iphoneos', '--show-sdk-path'))
        sdk_version = query('xcrun', '--sdk', 'iphoneos', '--show-sdk-version')
        compiler = query('xcrun', '--sdk', 'iphoneos', '--find', 'clang++')
    except subprocess.CalledProcessError:
        parser.exit(2, 'Build blocked: iPhoneOS SDK/toolchain unavailable; no app or IPA produced.\n')
    manifest = json.loads(a.sample_report.read_text())['manifest']
    if not manifest or sum(row['bytes'] for row in manifest) > 1024*1024:
        parser.error('initial lab requires a representative seed of at most 1 MiB')
    os.umask(0o077)
    app = output / 'Payload' / 'RR3ResourceLab.app'
    app.mkdir(parents=True, mode=0o700)
    sources = [repo/'native/RRResourceRuntime.mm', repo/'native/ios/ResourceLabApp.mm']
    identities = {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in [*sources, repo/'native/RRResourceRuntime.h', Path(__file__).resolve()]}
    seed_hash = hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
    build_id = hashlib.sha256(json.dumps({'sources':identities,'seed':seed_hash,
        'sdk':sdk_version,'minimum_os':a.min_ios},sort_keys=True).encode()).hexdigest()[:16]
    info = {'CFBundleExecutable':'RR3ResourceLab', 'CFBundleIdentifier':'org.rr3preservation.resourcelab',
            'CFBundleName':'RR3ResourceLab', 'CFBundleDisplayName':'RR3 Resource Lab',
            'CFBundlePackageType':'APPL', 'CFBundleVersion':'1', 'CFBundleShortVersionString':'0.1',
            'MinimumOSVersion':a.min_ios, 'LSRequiresIPhoneOS':True, 'UIDeviceFamily':[2],
            'UIRequiredDeviceCapabilities':['arm64'], 'DTPlatformName':'iphoneos',
            'DTSDKName':'iphoneos'+sdk_version, 'RRBuildID':build_id,
            'UILaunchScreen':{},
            'UISupportedInterfaceOrientations~ipad':['UIInterfaceOrientationPortrait',
                'UIInterfaceOrientationPortraitUpsideDown','UIInterfaceOrientationLandscapeLeft','UIInterfaceOrientationLandscapeRight'],
            'UIApplicationSceneManifest':{'UIApplicationSupportsMultipleScenes':False,
                'UISceneConfigurations':{'UIWindowSceneSessionRoleApplication':[
                    {'UISceneConfigurationName':'Resource Lab','UISceneDelegateClassName':'RRLabSceneDelegate'}]}}}
    (app/'Info.plist').write_bytes(plistlib.dumps(info))
    for row in manifest:
        source = checked_path(seed, row['path'])
        target = app/'ResourceSeed'/row['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open('rb') as src, target.open('xb') as dst:
            shutil.copyfileobj(src, dst, 65536)
        if target.stat().st_size != row['bytes'] or hashlib.sha256(target.read_bytes()).hexdigest() != row['sha256']:
            raise SystemExit('Copied lab seed failed baseline integrity check')
        target.chmod(0o644)
    (app/'seed-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    command = [compiler, '-target', 'arm64-apple-ios'+a.min_ios, '-isysroot', str(sdk),
               '-std=c++17', '-fobjc-arc', '-fblocks', '-Wno-deprecated-declarations',
               '-Wall', '-Wextra', '-Werror', '-I', str(repo/'native'), *map(str,sources),
               '-framework','Foundation','-framework','UIKit','-Wl,-no_adhoc_codesign',
               '-o',str(app/'RR3ResourceLab')]
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=120)
    (output/'build.txt').write_text(result.stdout+result.stderr)
    record = {'build_id':build_id,'target':'arm64 iPadOS UIKit lab','sdk_version':sdk_version,
              'minimum_os':a.min_ios,'source_sha256':identities,'seed_files':len(manifest),
              'seed_manifest_sha256':seed_hash,
              'seed_bytes':sum(row['bytes'] for row in manifest),'compiler_exit':result.returncode,
              'signing':'not performed; linker automatic ad-hoc signing disabled',
              'installed':False,'runtime_tested':False}
    if result.returncode == 0:
        ipa = output/'RR3ResourceLab-unsigned.ipa'
        with zipfile.ZipFile(ipa,'x',compression=zipfile.ZIP_DEFLATED) as archive:
            for file in sorted((output/'Payload').rglob('*')):
                if file.is_file():archive.write(file,file.relative_to(output).as_posix())
        with zipfile.ZipFile(ipa) as archive:
            assert archive.testzip() is None
        record['ipa_sha256'] = hashlib.sha256(ipa.read_bytes()).hexdigest()
        record['ipa_bytes'] = ipa.stat().st_size
    (output/'result.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k not in ['source_sha256','ipa_sha256']}))
    if result.returncode:
        raise SystemExit('iPadOS compiler failed; private build.txt retained for diagnosis.')


if __name__ == '__main__':
    main()
