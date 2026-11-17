"""Stream the complete preserved collection into one private ZIP64 IPA.

Uses existing inventory hashes; never copies an unpacked asset tree or signs,
installs, modifies originals, or migrates preserved player/SDK state.
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
from preservation_baseline import signature


def runtime_resource(name):
    if name.endswith('.bak') or '.DS_Store' in name.split('/'):
        return False
    return (name.split('/')[0] in ('Tracks','vehicles','gui_assets','Shaders')
            or name.startswith('customisation/textures/')
            or name in ('asset_list_base.txtCache.txt','asset_list_updates.txt',
                'asset_list_updates.info','tags/app_version','SpeedRush_TV_commercial.mp4',
                'data/upgrade_discount_popups.dat.nct'))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('prepared_ipa',type=Path);p.add_argument('cache',type=Path)
    p.add_argument('inventory',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();repo=Path(__file__).resolve().parents[1];out=a.output.resolve()
    if out.exists() or out.is_relative_to(repo) or out.is_relative_to(a.cache.resolve()):
        p.error('Output must be new, private, outside repository/source')
    os.umask(0o077);out.mkdir(mode=0o700)
    rows=[json.loads(l) for l in a.inventory.open()]
    rows=[dict(x,path=x['path'][7:]) for x in rows if x['path'].startswith('Caches/') and x['type']=='file']
    assert len(rows)==26043
    manifest=[{'path':x['path'],'bytes':x['size'],'sha256':x['sha256']} for x in rows if runtime_resource(x['path'])]
    names={x['path'] for x in rows};active={x['path'] for x in manifest}
    catalog=(a.cache/'asset_list_base.txtCache.txt').read_bytes()[8:].decode().splitlines()[1:]
    required={line.split('\t')[0].lstrip('/') for line in catalog if line}
    assert required<=active, 'A catalogue resource is not in runtime manifest'
    total=sum(x['size'] for x in rows)
    assert shutil.disk_usage(out).free>total+a.prepared_ipa.stat().st_size+2*1024**3
    sources=[repo/'native/RRResourceRuntime.mm',repo/'native/ios/RR3Bootstrap.mm']
    hashes={str(x.relative_to(repo)):hashlib.sha256(x.read_bytes()).hexdigest()
        for x in [*sources,repo/'native/RRResourceRuntime.h',Path(__file__).resolve()]}
    build_id=hashlib.sha256(json.dumps({'sources':hashes,'manifest':manifest},sort_keys=True).encode()).hexdigest()[:16]
    env=dict(os.environ,DEVELOPER_DIR='/Applications/Xcode.app/Contents/Developer')
    def query(*args):return subprocess.run(args,env=env,capture_output=True,text=True,check=True).stdout.strip()
    sdk=query('xcrun','--sdk','iphoneos','--show-sdk-path')
    compiler=query('xcrun','--sdk','iphoneos','--find','clang++')
    framework=out/'RR3Initializer';command=[compiler,'-target','arm64-apple-ios15.0','-isysroot',sdk,
        '-std=c++17','-fobjc-arc','-fblocks','-Wno-deprecated-declarations','-Wall','-Wextra','-Werror',
        '-I',str(repo/'native'),*map(str,sources),'-dynamiclib','-framework','Foundation','-framework','UIKit',
        '-Wl,-no_adhoc_codesign','-Wl,-install_name,@rpath/RR3Initializer.framework/RR3Initializer',
        '-Wl,-exported_symbol,_UIApplicationMain','-o',str(framework)]
    result=subprocess.run(command,env=env,capture_output=True,text=True)
    (out/'build.txt').write_text(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError('Native compile failed; see private build.txt')
    app='Payload/RealRacing3.app';destination=out/'RR3-Restored-full-unsigned.ipa'
    record={'build_id':build_id,'preserved_files':len(rows),'preserved_bytes':total,
        'runtime_files':len(manifest),'runtime_bytes':sum(x['bytes'] for x in manifest),
        'inactive_preserved_files':len(rows)-len(manifest),'catalogue_paths_covered':len(required),
        'source_hashes':hashes,'sdk':query('xcrun','--sdk','iphoneos','--show-sdk-version'),
        'signed':False,'installed':False}
    (out/'build-record.json').write_text(json.dumps(record,indent=2)+'\n')
    (out/'runtime-manifest.json').write_text(json.dumps(manifest,separators=(',',':')))
    print(json.dumps({k:v for k,v in record.items() if k!='source_hashes'}),flush=True)
    with zipfile.ZipFile(a.prepared_ipa) as old,zipfile.ZipFile(destination,'x',allowZip64=True) as archive:
        info=plistlib.loads(old.read(app+'/Info.plist'))
        assert info['CFBundleIdentifier']=='org.rr3preservation.restored'
        info.update(RR3InitializerMode='full-pre-nib-v1',RR3InitializerBuild=build_id,
                    RR3FirebaseConfigResource='GoogleService-Info-na')
        replacements={app+'/Info.plist':plistlib.dumps(info,fmt=plistlib.FMT_BINARY),
            app+'/Frameworks/RR3Initializer.framework/RR3Initializer':framework.read_bytes(),
            app+'/rr3-seed-manifest.json':json.dumps(manifest,separators=(',',':')).encode()}
        for item in old.infolist():
            if item.filename.startswith(app+'/RR3ResourceSeed/'):continue
            if item.is_dir():continue
            if item.filename in replacements:archive.writestr(item,replacements[item.filename]);continue
            with old.open(item) as src,archive.open(item,'w',force_zip64=item.file_size>=2**31) as dst:
                shutil.copyfileobj(src,dst,1048576)
        for i,row in enumerate(rows):
            source=a.cache/row['path'];before=source.lstat()
            assert signature(before)==row['signature'], 'Source changed since inventory: '+row['path']
            target=app+'/RR3ResourceSeed/'+row['path']
            archive.write(source,target,compress_type=zipfile.ZIP_STORED)
            assert signature(source.lstat())==row['signature']
            if i%5000==0:print('Packaged preserved files:',i,flush=True)
    with zipfile.ZipFile(destination) as z:
        seeds=[x for x in z.infolist() if x.filename.startswith(app+'/RR3ResourceSeed/')]
        assert len(seeds)==len(rows) and sum(x.file_size for x in seeds)==total
        assert z.testzip() is None
        assert plistlib.loads(z.read(app+'/PlugIns/todayWidget.appex/Info.plist'))['CFBundleIdentifier']=='org.rr3preservation.restored.widget'
    record.update(archive_crc_pass=True,seed_collection_complete=True,ipa_bytes=destination.stat().st_size)
    (out/'build-record.json').write_text(json.dumps(record,indent=2)+'\n')
    print('FULL IPA COMPLETE: '+str(destination),flush=True)


if __name__=='__main__':main()
