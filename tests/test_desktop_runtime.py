import sys,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import desktop_runtime as r
from fastapi import HTTPException
image=SimpleNamespace(attrs={'Config':{'Labels':{'lab.runtime.profile':r.PROFILE}}})
client=MagicMock();client.version.return_value={'Version':'26.1.5+dfsg1'}
context={'memory_mb':1536,'shm_mb':256,'pids':512}
def rejected(call):
    try:call()
    except HTTPException as exc:assert exc.status_code==503
    else:raise AssertionError('Expected refusal')
with patch.dict(r.os.environ,{'LAB_NETWORK_ISOLATION':'required','PERSISTENT_STORAGE_BACKEND':'quota'}):
    runtime=r.options(client,image,context)
    assert runtime['read_only'] and runtime['memswap_limit']=='1536m'
    profile=json.loads(runtime['security_opt'][1].removeprefix('seccomp='))
    assert profile['defaultAction']=='SCMP_ACT_ERRNO'
    home={'volumes':{'existing-home-quota':{'bind':'/config','mode':'rw'}}}
    result=r.merge_home(runtime,home)
    assert result['volumes']==home['volumes'] and '/config' not in result['tmpfs']
    result=r.merge_home(runtime,{'tmpfs':{'/config':'rw,size=300m,mode=1777'}})
    assert result['tmpfs']['/config']=='rw,size=300m,mode=1777'
    assert all(result['tmpfs'][key]==value for key,value in r.RUNTIME_TMPFS.items())
    assert '/config' not in runtime['tmpfs']
    rejected(lambda:r.merge_home(runtime,{'tmpfs':{'/run':'rw'}}))
    rejected(lambda:r.options(client,image,{**context,'memory_mb':768}))
    with patch.dict(r.os.environ,{'LAB_NETWORK_ISOLATION':'off'}):rejected(lambda:r.options(client,image,context))
    with patch.dict(r.os.environ,{'PERSISTENT_STORAGE_BACKEND':'legacy'}):rejected(lambda:r.merge_home(runtime,home))
    client.version.return_value={'Version':'27.0.0'}
    rejected(lambda:r.options(client,image,context))
    client.version.return_value={'Version':'26.1.5'}
    with patch.object(r.Path,'read_text',return_value='{}'):rejected(lambda:r.options(client,image,context))
assert r.options(client,SimpleNamespace(attrs={'Config':{}}),{})=={'security_opt':['no-new-privileges:true']}
rejected(lambda:r.options(client,SimpleNamespace(attrs={'Config':{'Labels':{'lab.runtime.profile':'unknown'}}}),context))
print('PASS: runtime limits, profile integrity, storage merge, version and network gates; legacy unchanged.')

lite=SimpleNamespace(attrs={'Config':{'Labels':{'lab.runtime.profile':r.LITE_PROFILE}}})
small={'memory_mb':768,'shm_mb':128,'pids':256}
with patch.dict(r.os.environ,{'LAB_NETWORK_ISOLATION':'required','PERSISTENT_STORAGE_BACKEND':'quota'}):
    runtime=r.options(client,lite,small)
    assert runtime['read_only'] and runtime['memswap_limit']=='768m'
    assert runtime['security_opt'][1].startswith('seccomp=')
    for key in small:
        rejected(lambda:r.options(client,lite,{**small,key:small[key]-1}))
    rejected(lambda:r.options(client,image,small))
print('PASS: lite profile uses separate resource minima without weakening CSE limits')

import sqlite3
with sqlite3.connect(':memory:') as db, patch.dict(r.os.environ,{'LAB_CAPACITY_MODE':'pi-lite3'}):
    db.execute('CREATE TABLE sessions(status TEXT,capacity_units INTEGER)')
    lite_context={**small,'cpu_millis':1000,'home_mb':128}
    assert r.admission_units(db,lite,lite_context)==1
    db.execute("INSERT INTO sessions VALUES ('starting',1),('active',1)")
    assert r.admission_units(db,lite,lite_context)==1
    def full(image,ctx):
        try:r.admission_units(db,image,ctx)
        except HTTPException as exc:assert exc.status_code==429
        else:raise AssertionError('Over-capacity admitted')
    full(image,lite_context)
    full(lite,{**lite_context,'memory_mb':1024})
    db.execute("INSERT INTO sessions VALUES ('active',1)")
    full(lite,lite_context)
    db.execute('DELETE FROM sessions')
    assert r.admission_units(db,image,context)==3
    db.execute("INSERT INTO sessions VALUES ('active',3)")
    full(lite,lite_context);full(image,context)
    db.execute("UPDATE sessions SET capacity_units=NULL")
    full(lite,lite_context)
    db.execute("UPDATE sessions SET status='expired'")
    assert r.admission_units(db,lite,lite_context)==1
print('PASS: Pi admission allows 3 lite OR 1 other, counts startup/legacy reservations, and treats enlarged lite templates as heavy')
