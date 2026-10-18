import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import disk_guard
from fastapi import HTTPException


def check(free,total,inodes=500,files=1000):
    with patch.object(disk_guard.shutil,'disk_usage',return_value=SimpleNamespace(total=total*1024**3)), \
         patch.object(disk_guard.os,'statvfs',return_value=SimpleNamespace(f_bavail=int(free*1024**3),f_frsize=1,f_files=files,f_favail=inodes)):
        return disk_guard.snapshot('/data/sessions.db')

assert all(c['status']=='OK' for c in check(10,50))
assert all(c['status']=='WARNING' for c in check(4,50))
assert all(c['status']=='CRITICAL' for c in check(1,50))
assert all(c['status']=='CRITICAL' for c in check(3,100))
assert all(c['status']=='CRITICAL' for c in check(10,50,1))
with patch.object(disk_guard.os,'statvfs',side_effect=OSError('unreadable')):
    assert all(c['status']=='UNAVAILABLE' for c in disk_guard.snapshot('/tmp/db'))
for status in ('CRITICAL','UNAVAILABLE'):
    with patch.object(disk_guard,'snapshot',return_value=[{'status':'OK'},{'status':status}]):
        try: disk_guard.require_space('/data/db')
        except HTTPException as e: assert e.status_code==503
        else: raise AssertionError('Admission must fail closed')
with patch.object(disk_guard,'snapshot',return_value=[{'status':'WARNING'}]):
    disk_guard.require_space('/data/db')
print('PASS: disk thresholds, inode exhaustion, unreadable filesystem and admission checks')
