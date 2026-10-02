"""Prepare this ISO's Acrobat update for Wine's MSI media selection.

Run with the embedded Windows Python under Wine. The original MSI/MSP remain
unchanged. The added transform changes only Media[DiskId=6].LastSequence.
See docs/compatibility.md for the retained fixes and their scope.
"""
import ctypes as C
from ctypes import wintypes as W
from pathlib import Path
import json
import shutil
import sys
import struct
import hashlib
import os

if os.name != 'nt':
    raise SystemExit('Run this helper using .local/python-windows/python.exe under Wine.')

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / '.local' / 'installer' / 'wine-compatible'
OUT.mkdir(exist_ok=True)
MEDIA = ROOT / '.local' / 'installer' / 'Adobe Acrobat'
SOURCE_HASHES = {
    'AcroPro.msi': '089dc9a23f5eb868a6f6b8a6a901c2a29faef113ad296c8d40f6ce9de60f4b2d',
    'AcrobatDCx64Upd2600221931.msp': '7f8f1e7fe86a0282e773d3cfca8cfc17293a444226f9a653938b7de671d9c9fb',
}
def digest(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()

for name, expected in SOURCE_HASHES.items():
    if digest(MEDIA/name) != expected:
        raise SystemExit(f'This compatibility transform does not support the supplied {name}.')

ole = C.WinDLL('ole32')
msi = C.WinDLL('msi')

def check(result):
    if result:
        raise RuntimeError(f'Windows API returned {result:#x}')

def function(dll, name, args, result=W.UINT):
    fn = getattr(dll, name)
    fn.argtypes, fn.restype = args, result
    return fn

def method(obj, index, args, result=C.c_long):
    table = C.cast(obj, C.POINTER(C.POINTER(C.c_void_p))).contents
    return C.WINFUNCTYPE(result, C.c_void_p, *args)(table[index])

def stream_name(name):
    alphabet='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz._'
    out='\u4840'
    while name:
        first=alphabet.index(name[0]);name=name[1:]
        if name:
            second=alphabet.index(name[0]);name=name[1:]
            out+=chr(0x3800+first+(second<<6))
        else:
            out+=chr(0x4800+first)
    return out

def make_media_transform(source, target):
    source_storage, target_storage=C.c_void_p(),C.c_void_p()
    check(ole.StgOpenStorage(str(source),None,0x20,None,0,C.byref(source_storage)))
    check(ole.StgCreateDocfile(str(target),0x1012,0,C.byref(target_storage)))
    clsid=C.create_string_buffer(16)
    check(function(ole,'ReadClassStg',[C.c_void_p,C.c_void_p],C.c_long)(source_storage,clsid))
    check(method(target_storage,15,[C.c_void_p])(target_storage,clsid))
    def write(name,data):
        stream=C.c_void_p()
        check(method(target_storage,3,[W.LPCWSTR,W.DWORD,W.DWORD,W.DWORD,C.POINTER(C.c_void_p)])(
            target_storage,name,0x1012,0,0,C.byref(stream)))
        count=W.ULONG();buffer=C.create_string_buffer(data)
        check(method(stream,4,[C.c_void_p,W.ULONG,C.POINTER(W.ULONG)])(stream,buffer,len(data),C.byref(count)))
        assert count.value==len(data)
        method(stream,2,[],W.ULONG)(stream)
    for name in [stream_name('_StringPool'),stream_name('_StringData'),'\x05SummaryInformation']:
        stream=C.c_void_p()
        check(method(source_storage,4,[W.LPCWSTR,C.c_void_p,W.DWORD,W.DWORD,C.POINTER(C.c_void_p)])(
            source_storage,name,None,0x10,0,C.byref(stream)))
        chunks=[]
        while True:
            buffer=C.create_string_buffer(65536);count=W.ULONG()
            result=method(stream,3,[C.c_void_p,W.ULONG,C.POINTER(W.ULONG)])(stream,buffer,len(buffer),C.byref(count))
            if result<0:check(result)
            chunks.append(buffer.raw[:count.value])
            if count.value<len(buffer):break
        method(stream,2,[],W.ULONG)(stream)
        write(name,b''.join(chunks))
    # The original transform's !Media record is 02 00 06 80 48 af.
    # Keep its update mask and disk key, restoring the base cabinet's end.
    write(stream_name('Media'),struct.pack('<HHH',2,0x8000+6,0x8000+6406))
    check(method(target_storage,9,[W.DWORD])(target_storage,0))
    for obj in [target_storage,source_storage]:method(obj,2,[],W.ULONG)(obj)

storage = C.c_void_p()
check(function(ole, 'StgOpenStorage', [W.LPCWSTR,C.c_void_p,W.DWORD,C.c_void_p,W.DWORD,C.POINTER(C.c_void_p)], C.c_long)(
    str(MEDIA/'AcrobatDCx64Upd2600221931.msp'),None,0x20,None,0,C.byref(storage)))
transforms = []
for name in ['TGT_04ToUPG_04', '#TGT_04ToUPG_04']:
    sub, dest = C.c_void_p(), C.c_void_p()
    check(method(storage,6,[W.LPCWSTR,C.c_void_p,W.DWORD,C.c_void_p,W.DWORD,C.POINTER(C.c_void_p)])(
        storage,name,None,0x10,None,0,C.byref(sub)))
    path=OUT/(name.replace('#','patch-')+'.mst')
    check(function(ole,'StgCreateDocfile',[W.LPCWSTR,W.DWORD,W.DWORD,C.POINTER(C.c_void_p)],C.c_long)(str(path),0x1012,0,C.byref(dest)))
    check(method(sub,7,[W.DWORD,C.c_void_p,C.c_void_p,C.c_void_p])(sub,0,None,None,dest))
    check(method(dest,9,[W.DWORD])(dest,0))
    for obj in [dest,sub]:method(obj,2,[],W.ULONG)(obj)
    transforms.append(path)
method(storage,2,[],W.ULONG)(storage)

path=OUT/'inspect.msi'
shutil.copyfile(MEDIA/'AcroPro.msi',path)
db=W.UINT()
check(function(msi,'MsiOpenDatabaseW',[W.LPCWSTR,C.c_void_p,C.POINTER(W.UINT)])(str(path),C.c_void_p(1),C.byref(db)))
for transform in transforms:
    check(function(msi,'MsiDatabaseApplyTransformW',[W.UINT,W.LPCWSTR,W.INT])(db,str(transform),0))
    print('Applied',transform.name,flush=True)

open_view=function(msi,'MsiDatabaseOpenViewW',[W.UINT,W.LPCWSTR,C.POINTER(W.UINT)])
execute=function(msi,'MsiViewExecute',[W.UINT,W.UINT])
fetch=function(msi,'MsiViewFetch',[W.UINT,C.POINTER(W.UINT)])
field_count=function(msi,'MsiRecordGetFieldCount',[W.UINT])
get_string=function(msi,'MsiRecordGetStringW',[W.UINT,W.UINT,W.LPWSTR,C.POINTER(W.DWORD)])
close=function(msi,'MsiCloseHandle',[W.UINT])
for sql in ["SELECT * FROM `Media`", "SELECT * FROM `_Columns` WHERE `Table`='Media'", "SELECT * FROM `_Columns` WHERE `Table`='Patch'", "SELECT * FROM `Patch` WHERE `File_`='AcroPDF.FRA'"]:
    view=W.UINT();check(open_view(db,sql,C.byref(view)));check(execute(view,0))
    print(sql,flush=True)
    while True:
        record=W.UINT();r=fetch(view,C.byref(record))
        if r==259:break
        check(r);values=[]
        for i in range(1,field_count(record)+1):
            buf=C.create_unicode_buffer(2048);size=W.DWORD(len(buf))
            result=get_string(record,i,buf,C.byref(size))
            values.append(buf.value if result==0 else f'error:{result}')
        print(json.dumps(values),flush=True);close(record)
    close(view)
if '--prepare-update' in sys.argv:
    commit=function(msi,'MsiDatabaseCommit',[W.UINT])
    check(commit(db));close(db)
    correction=OUT/'WineFixMedia.mst'
    make_media_transform(transforms[1],correction)
    verify=W.UINT()
    check(msi.MsiOpenDatabaseW(str(path),C.c_void_p(1),C.byref(verify)))
    check(msi.MsiDatabaseApplyTransformW(verify,str(correction),0))
    view=W.UINT()
    check(open_view(verify,'SELECT `LastSequence` FROM `Media` WHERE `DiskId`=6',C.byref(view)))
    check(execute(view,0));record=W.UINT();check(fetch(view,C.byref(record)))
    get_integer=function(msi,'MsiRecordGetInteger',[W.UINT,W.UINT],W.INT)
    assert get_integer(record,1)==6406, 'Correction transform verification failed'
    close(record);close(view);close(verify)
    update=OUT/'AcrobatDCx64Upd2600221931-wine.partial.msp'
    shutil.copyfile(MEDIA/'AcrobatDCx64Upd2600221931.msp',update)
    patch_db=W.UINT()
    check(msi.MsiOpenDatabaseW(str(update),C.c_void_p(34),C.byref(patch_db)))
    check(open_view(patch_db,'INSERT INTO `_Storages` (`Name`,`Data`) VALUES (?,?)',C.byref(view)))
    record=function(msi,'MsiCreateRecord',[W.UINT])(2)
    check(function(msi,'MsiRecordSetStringW',[W.UINT,W.UINT,W.LPCWSTR])(record,1,'WineFixMedia'))
    check(function(msi,'MsiRecordSetStreamW',[W.UINT,W.UINT,W.LPCWSTR])(record,2,str(correction)))
    check(execute(view,record));close(record);close(view)
    summary=W.UINT()
    check(function(msi,'MsiGetSummaryInformationW',[W.UINT,W.LPCWSTR,W.UINT,C.POINTER(W.UINT)])(
        patch_db,None,1,C.byref(summary)))
    buffer=C.create_unicode_buffer(4096);size=W.DWORD(len(buffer));kind=W.UINT()
    check(function(msi,'MsiSummaryInfoGetPropertyW',[W.UINT,W.UINT,C.POINTER(W.UINT),C.c_void_p,C.c_void_p,W.LPWSTR,C.POINTER(W.DWORD)])(
        summary,8,C.byref(kind),None,None,buffer,C.byref(size)))
    names=buffer.value+';:WineFixMedia'
    check(function(msi,'MsiSummaryInfoSetPropertyW',[W.UINT,W.UINT,W.UINT,W.INT,C.c_void_p,W.LPCWSTR])(
        summary,8,30,0,None,names))
    check(function(msi,'MsiSummaryInfoPersist',[W.UINT])(summary));close(summary)
    check(commit(patch_db));close(patch_db)
    final=OUT/'AcrobatDCx64Upd2600221931-wine.msp'
    update.replace(final)
    manifest={
        'version':'26.002.21931',
        'inputs':SOURCE_HASHES,
        'output_sha256':digest(final),
        'transform':{'table':'Media','DiskId':6,'LastSequence':{'from':12104,'to':6406}},
    }
    (OUT/'media-fix.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    update=final
    print('Prepared compatibility update:',update,flush=True)
else:
    close(db)
