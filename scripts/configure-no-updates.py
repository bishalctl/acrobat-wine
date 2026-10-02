"""Apply and verify update restrictions inside this project's Wine profile."""
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import winreg as R

ROOT = Path(__file__).resolve().parent.parent
report = {'policies': [], 'updater_modes': [], 'service': {}, 'run_entries_removed': []}
for path in [r'SOFTWARE\Policies\Adobe\Adobe Acrobat\DC\FeatureLockDown',
             r'SOFTWARE\Wow6432Node\Policies\Adobe\Adobe Acrobat\DC\FeatureLockDown']:
    with R.CreateKeyEx(R.HKEY_LOCAL_MACHINE, path, 0, R.KEY_ALL_ACCESS) as key:
        R.SetValueEx(key, 'bUpdater', 0, R.REG_DWORD, 0)
        report['policies'].append({'path': path, 'bUpdater': R.QueryValueEx(key, 'bUpdater')[0]})

for path in [r'SOFTWARE\Adobe\Adobe ARM\Legacy\Acrobat',
             r'SOFTWARE\Wow6432Node\Adobe\Adobe ARM\Legacy\Acrobat']:
    try:
        with R.OpenKey(R.HKEY_LOCAL_MACHINE, path) as parent:
            index = 0
            while True:
                try:
                    name = R.EnumKey(parent, index)
                except OSError:
                    break
                index += 1
                with R.OpenKey(parent, name, 0, R.KEY_ALL_ACCESS) as key:
                    R.SetValueEx(key, 'Mode', 0, R.REG_DWORD, 0)
                    report['updater_modes'].append({'path': path + '\\' + name,
                                                    'Mode': R.QueryValueEx(key, 'Mode')[0]})
    except FileNotFoundError:
        pass

service_path = r'SYSTEM\CurrentControlSet\Services\AdobeARMservice'
try:
    with R.OpenKey(R.HKEY_LOCAL_MACHINE, service_path, 0, R.KEY_ALL_ACCESS) as key:
        R.SetValueEx(key, 'Start', 0, R.REG_DWORD, 4)
        report['service'] = {'installed': True, 'Start': R.QueryValueEx(key, 'Start')[0]}
except FileNotFoundError:
    report['service'] = {'installed': False}

for path in [r'SOFTWARE\Microsoft\Windows\CurrentVersion\Run',
             r'SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Run']:
    try:
        with R.OpenKey(R.HKEY_LOCAL_MACHINE, path, 0, R.KEY_ALL_ACCESS) as key:
            for name in ['Adobe ARM', 'Acrobat Assistant 8.0']:
                try:
                    R.DeleteValue(key, name)
                    report['run_entries_removed'].append(path + '\\' + name)
                except FileNotFoundError:
                    pass
    except FileNotFoundError:
        pass

with R.CreateKeyEx(R.HKEY_CURRENT_USER, r'Software\Wine\DllOverrides', 0, R.KEY_ALL_ACCESS) as key:
    report['blocked_executables'] = {}
    for name in ['AdobeARM.exe', 'AdobeARMHelper.exe', 'armsvc.exe']:
        R.SetValueEx(key, '*' + name, 0, R.REG_SZ, '')
        report['blocked_executables'][name] = R.QueryValueEx(key, '*' + name)[0] == ''

assert all(p['bUpdater'] == 0 for p in report['policies'])
assert all(p['Mode'] == 0 for p in report['updater_modes'])
assert not report['service']['installed'] or report['service']['Start'] == 4
assert all(report['blocked_executables'].values())
(ROOT / 'state/update-settings.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps(report, indent=2))
