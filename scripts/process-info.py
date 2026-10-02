"""Read command lines and CPU counters for installer processes in this prefix."""
import csv,ctypes as C,json,struct
from ctypes import wintypes as W
from pathlib import Path
k=C.WinDLL('kernel32',use_last_error=True);n=C.WinDLL('ntdll')
k.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];k.OpenProcess.restype=W.HANDLE
k.CloseHandle.argtypes=[W.HANDLE]
k.ReadProcessMemory.argtypes=[W.HANDLE,C.c_void_p,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)]
k.GetProcessTimes.argtypes=[W.HANDLE]+[C.POINTER(W.FILETIME)]*4
k.GetExitCodeProcess.argtypes=[W.HANDLE,C.POINTER(W.DWORD)]
n.NtQueryInformationProcess.argtypes=[W.HANDLE,W.ULONG,C.c_void_p,W.ULONG,C.POINTER(W.ULONG)]
n.NtQueryInformationProcess.restype=C.c_long
class PBI(C.Structure):
 _fields_=[('reserved',C.c_void_p),('peb',C.c_void_p),('reserved2',C.c_void_p*2),('pid',C.c_void_p),('reserved3',C.c_void_p)]
root=Path(__file__).resolve().parent.parent
rows=[]
for row in csv.reader((root/'state/installer-processes.csv').read_text().splitlines()):
 if len(row)<2 or row[0].lower() not in ['setup.exe','crack.exe','msiexec.exe','acrobat.exe','winedbg.exe']:continue
 pid=int(row[1]);result={'name':row[0],'pid':pid};h=k.OpenProcess(0x410,False,pid)
 if not h:result['error']=C.get_last_error();rows.append(result);continue
 try:
  def read(address,size):
   b=C.create_string_buffer(size);got=C.c_size_t()
   if not k.ReadProcessMemory(h,address,b,size,C.byref(got)) or got.value!=size:raise OSError(C.get_last_error())
   return b.raw
  basic=PBI();status=n.NtQueryInformationProcess(h,0,C.byref(basic),C.sizeof(basic),None)
  if status:raise OSError(hex(status&0xffffffff))
  wow=C.c_size_t();n.NtQueryInformationProcess(h,26,C.byref(wow),C.sizeof(wow),None)
  bits=32 if wow.value else 64;peb=wow.value or basic.peb
  params=struct.unpack('<I' if bits==32 else '<Q',read(peb+(0x10 if bits==32 else 0x20),bits//8))[0]
  length,maximum,address=struct.unpack('<HHI' if bits==32 else '<HH4xQ',read(params+(0x40 if bits==32 else 0x70),8 if bits==32 else 16))
  result.update(bits=bits,command=read(address,length).decode('utf-16-le',errors='replace'))
  times=[W.FILETIME() for _ in range(4)]
  if k.GetProcessTimes(h,*[C.byref(t) for t in times]):result['cpu_seconds']=sum((t.dwHighDateTime<<32)|t.dwLowDateTime for t in times[2:])/1e7
  code=W.DWORD();k.GetExitCodeProcess(h,C.byref(code));result['exit_code']=hex(code.value)
 except (OSError,ValueError) as e:result['error']=str(e)
 finally:k.CloseHandle(h)
 rows.append(result)
print(json.dumps(rows,indent=2))
