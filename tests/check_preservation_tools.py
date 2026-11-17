"""Synthetic preservation checks; no original game data or live source paths."""
import json, os, plistlib, struct, subprocess, tempfile, zipfile
from pathlib import Path
scripts=Path(__file__).resolve().parents[1]/'scripts'
def run(script,*args):
 p=subprocess.run(['python3',str(scripts/script),*map(str,args)],text=True,capture_output=True)
 assert p.returncode==0,(script,p.stderr)
 return p
with tempfile.TemporaryDirectory() as d:
 root=Path(d);source=root/'source';output=root/'output';source.mkdir();output.mkdir()
 (source/'a').write_bytes(b'identical');(source/'b').write_bytes(b'identical');(source/'empty').touch();(source/'link').symlink_to('a')
 before={p.name:p.lstat() for p in source.iterdir()}
 run('preservation_baseline.py',source,output)
 s=json.loads((output/'summary.json').read_text());assert (s['hashed'],s['duplicate_groups'],len(s['nonregular']))==(3,1,1)
 run('preservation_baseline.py',source,output)
 s=json.loads((output/'summary.json').read_text());assert (s['hashed'],s['reused_hashes'])==(0,3)
 for p in source.iterdir():
  a,b=before[p.name],p.lstat();assert (a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(b.st_size,b.st_mtime_ns,b.st_ctime_ns)
 (source/'b').write_bytes(b'changed')
 run('preservation_baseline.py',source,output)
 s=json.loads((output/'summary.json').read_text());assert (s['hashed'],s['reused_hashes'],s['duplicate_groups'])==(1,2,0)
 print('PASS: inventory, duplicate detection, symlink avoidance, unchanged-source stats, hash reuse, changed-file invalidation')
 ipa=source/'RealRacing3.ipa';out=root/'ipa-report';out.mkdir()
 with zipfile.ZipFile(ipa,'w',compression=zipfile.ZIP_STORED) as z:
  z.writestr('Payload/Test.app/Info.plist',plistlib.dumps({'CFBundleExecutable':'Test','CFBundleIdentifier':'test.invalid','CFBundleVersion':'1'}))
  z.writestr('Payload/Test.app/Test',struct.pack('<8I',0xfeedfacf,0x100000c,0,2,0,0,0,0))
  z.writestr('Payload/Test.app/marker',b'crc-test-content')
 run('inspect_ipa.py',ipa,out)
 r=json.loads((out/'ipa-inspection.json').read_text());assert r['crc_checked']==3 and not r['crc_errors'];assert r['applications'][0]['macho']['architecture']=='arm64'
 p=run('inspect_ipa.py',ipa,out);assert 'Reusing' in p.stdout
 b=ipa.read_bytes();ipa.write_bytes(b.replace(b'crc-test-content',b'crc-test-CONTENT'))
 run('inspect_ipa.py',ipa,out)
 r=json.loads((out/'ipa-inspection.json').read_text());assert len(r['crc_errors'])==1
 print('PASS: ZIP CRC, arm64 parsing, unchanged inspection reuse, corrupt member detection')
 cache=source/'Caches';(cache/'tags').mkdir(parents=True);(cache/'tags/app_version').write_text('1');(cache/'present').write_bytes(b'abc');(cache/'wrongsize').write_bytes(b'long')
 digest='a'*32
 (cache/'asset_list_base.txtCache.txt').write_bytes(b'\0'*8+f'2\n/present\t{digest}\n/wrongsize\t{digest}\n'.encode())
 (cache/'asset_list_updates.txt').write_text(f'/present\t{digest}\t3\t3\n')
 with zipfile.ZipFile(ipa,'w') as z:
  z.writestr('Payload/Test.app/res/asset_list_example.txt',f'/present\t{digest}\t3\t3\n/wrongsize\t{digest}\t2\t2\n/absent\t{digest}\t1\t1\n')
 run('preservation_baseline.py',source,output)
 run('compare_cache_metadata.py',source,output)
 r=json.loads((output/'cache-compatibility.json').read_text());assert r['catalogue_ipa_recorded_checksum_matches']==2;assert r['ipa_size_mismatches']==['/wrongsize'];assert r['ipa_paths_absent_from_cache']==['/absent'];assert r['update_records'][0]['size_matches']
 print('PASS: catalogue matching, missing-path detection, size mismatch, update metadata')
