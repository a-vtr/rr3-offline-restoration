"""Verify prepared ad-hoc components and reuse an existing rejected staging IPA.

No Apple-account signing, credentials, device access or new full game copy.
Only two ZIP entries and their central records are replaced in place, provided
the new compressed records fit their existing slots. Baseline IPA is read-only.
"""
import argparse
import copy
import io
import json
from pathlib import Path
import plistlib
import struct
import subprocess
import zipfile
from trace_resource_startup import Image


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline',type=Path);p.add_argument('prepared',type=Path)
    p.add_argument('existing_staging',type=Path);p.add_argument('templates',type=Path)
    a=p.parse_args()
    assert a.baseline.resolve()!=a.existing_staging.resolve()
    rejected=a.existing_staging.parent/'validation-failed.json'
    assert json.loads(rejected.read_text())['rejected'] is True
    results=[];updates={}
    with zipfile.ZipFile(a.baseline) as z:
        for name in ('RealRacing3','todayWidget'):
            path=a.prepared/name
            verify=subprocess.run(['codesign','--verify','--strict',str(path)],capture_output=True)
            ent=subprocess.run(['codesign','-d','--entitlements',':-',str(path)],capture_output=True)
            assert verify.returncode==ent.returncode==0
            expected=plistlib.loads((a.templates/(name+'-entitlements-intent.plist')).read_bytes())
            assert plistlib.loads(ent.stdout)==expected
            entry='Payload/RealRacing3.app/'+('RealRacing3' if name=='RealRacing3' else 'PlugIns/todayWidget.appex/todayWidget')
            before=Image(z.read(entry));data=path.read_bytes();after=Image(data)
            checked=0
            for key,(address,size,offset) in before.sections.items():
                if not offset:continue  # __bss/__common are virtual zero-fill, not file bytes.
                address2,size2,offset2=after.sections[key]
                assert (address,size)==(address2,size2)
                assert before.data[offset:offset+size]==data[offset2:offset2+size2]
                checked+=1
            updates[entry]=data
            results.append({'component':name,'adhoc_verify_pass':True,'apple_entitlement_read_pass':True,
                'experimental_groups_only':True,'file_backed_sections_unchanged':checked})
    plans=[]
    with zipfile.ZipFile(a.existing_staging) as z, a.existing_staging.open('rb') as src:
        entries=z.infolist();ordered=sorted(entries,key=lambda x:x.header_offset)
        spans={v.filename:(ordered[i+1].header_offset if i+1<len(ordered) else z.start_dir)-v.header_offset
               for i,v in enumerate(ordered)}
        central={};src.seek(z.start_dir)
        for item in entries:
            position=src.tell();h=src.read(46);assert h[:4]==b'PK\x01\x02'
            n,x,c=struct.unpack_from('<HHH',h,28);raw=h+src.read(n+x+c)
            central[item.filename]=(position,raw)
        for name,data in updates.items():
            item=z.getinfo(name);buffer=io.BytesIO()
            with zipfile.ZipFile(buffer,'w') as mini:mini.writestr(copy.copy(item),data)
            with zipfile.ZipFile(buffer) as mini:
                start=mini.start_dir;v=mini.infolist()[0]
                length=46+len(v.filename.encode())+len(v.extra)+len(v.comment)
            blob=buffer.getvalue();local=blob[:start];cd=bytearray(blob[start:start+length])
            assert len(local)<=spans[name], 'Replacement does not fit; no archive write performed'
            struct.pack_into('<I',cd,42,item.header_offset)
            cd_position,old_cd=central[name];assert len(cd)==len(old_cd)
            src.seek(item.header_offset);old_local=src.read(spans[name])
            # Small per-component rollback records, never another full IPA.
            (a.prepared/(Path(name).name+'-zip-slot-before.bin')).write_bytes(old_local)
            plans.append((item.header_offset,local.ljust(spans[name],b'\0'),old_local,cd_position,bytes(cd),old_cd))
    with a.existing_staging.open('r+b') as output:
        try:
            for offset,local,_,cd_position,cd,_ in plans:
                output.seek(offset);output.write(local);output.seek(cd_position);output.write(cd)
            output.flush()
            with zipfile.ZipFile(a.existing_staging) as check,zipfile.ZipFile(a.baseline) as baseline:
                assert check.testzip() is None
                for name,data in updates.items():assert check.read(name)==data
                for item in baseline.infolist():
                    if item.filename in updates:continue
                    other=check.getinfo(item.filename)
                    assert (item.CRC,item.file_size,item.compress_size)==(other.CRC,other.file_size,other.compress_size)
        except BaseException:
            for offset,_,old_local,cd_position,_,old_cd in plans:
                output.seek(offset);output.write(old_local);output.seek(cd_position);output.write(old_cd)
            output.flush();raise
    result={'components':results,'archive_crc_pass':True,'all_other_entries_unchanged':True,
        'baseline_untouched':True,'existing_rejected_archive_reused':True,'new_full_game_copy_created':False,
        'apple_team_provisioning_verified':False,'account_signed':False,'installed':False,
        'note':'Local ad-hoc preparation only; placeholder keychain prefix must become actual team on export.'}
    (a.prepared/'preparation-validation.json').write_text(json.dumps(result,indent=2)+'\n')
    rejected.write_text(json.dumps({'rejected':False,'replaced_by_verified_adhoc_preparation':True,
        'account_signed':False,'install_ready':False},indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':main()
