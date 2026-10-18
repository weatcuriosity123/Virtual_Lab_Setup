"""Exercise migration/retry/deletion with real temp files; mock privileged host operations."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('agent',Path(__file__).resolve().parents[1]/'host/storage_agent.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);a.STATE=root/'state';a.STATE.mkdir();a.POOL=root/'pool';a.POOL.mkdir()
    original=root/'original';original.mkdir();(original/'work.txt').write_text('student work')
    name='linux-lab-home-v1-'+'a'*64
    scope={'college_id':'college','classroom_id':'class','template_id':'cse'}
    labels=a.labels_for(name,scope)
    volumes={name:{'Driver':'local','Options':None,'Labels':labels,'Mountpoint':str(original)}}
    limit=[0];size=[0];commands=[]
    def fake_run(*args,**kwargs):
        commands.append(args)
        if args[0]=='setquota': limit[0]=int(args[4])*1024
        if args[0]=='rsync' and '-aH' in args:
            shutil.copy2(original/'work.txt',a.POOL/name/'work.txt')
        return ''
    def fake_usage(project):
        return {'used_bytes':size[0],'limit_bytes':limit[0],'used_inodes':1}
    with patch.object(a.os,'chown'), patch.object(a,'run',side_effect=fake_run), patch.object(a,'mounted',return_value='/dev/test'), patch.object(a,'inspect_volume',side_effect=lambda n:volumes.get(n)), patch.object(a,'usage',side_effect=fake_usage):
        db=a.db_open()
        first=a.ensure(db,name,scope,64)
        assert first['state']=='ready' and first['copied'] and first['limit_bytes']==64*1048576
        assert (a.POOL/name/'work.txt').read_text()=='student work'
        assert (original/'work.txt').read_text()=='student work'
        commands.clear()
        a.ensure(db,name,scope,128)
        assert not any(c[0]=='rsync' for c in commands), 'ready home must not be overwritten by old backup'
        size[0]=100*1048576
        try: a.ensure(db,name,scope,64);raise AssertionError('unsafe shrink accepted')
        except ValueError: pass
        size[0]=0
        a.purge(db,name)
        assert not (a.POOL/name).exists() and (original/'work.txt').exists()
        assert db.execute('SELECT state FROM homes WHERE name=?',(name,)).fetchone()[0]=='deleted'
        a.ensure(db,name,scope,64)
        assert not (a.POOL/name/'work.txt').exists(), 'deleted data resurrected from retained backup'
        # Invalid identity/scope cannot redirect privileged operations.
        try: a.ensure(db,name,{**scope,'college_id':'../../etc'},64);raise AssertionError('invalid scope accepted')
        except ValueError: pass
        with patch.object(a,'unattached',side_effect=ValueError('busy')):
            try: a.purge(db,name);raise AssertionError('attached deletion accepted')
            except ValueError: pass
        # Failed checksum verification keeps source and blocks ready state.
        second='linux-lab-home-v1-'+'b'*64
        other_labels=a.labels_for(second,scope)
        volumes[second]={'Driver':'local','Options':None,'Labels':other_labels,'Mountpoint':str(original)}
        def mismatch(*args,**kwargs):
            if args[0]=='rsync' and '-aHnc' in args:return '>fcs....... work.txt'
            if args[0]=='rsync':return ''
            return fake_run(*args,**kwargs)
        with patch.object(a,'run',side_effect=mismatch):
            try:a.ensure(db,second,scope,64);raise AssertionError('bad migration accepted')
            except ValueError:pass
        assert db.execute('SELECT state FROM homes WHERE name=?',(second,)).fetchone()[0]=='preparing'
        assert (original/'work.txt').exists()
        db.close()
    with patch.object(a,'mounted',side_effect=ValueError('pool missing')),patch.object(a,'db_open') as opening:
        try:a.dispatch({'op':'ensure','name':name,'scope':scope,'limit_mb':64});raise AssertionError('missing pool accepted')
        except ValueError:pass
        opening.assert_not_called()
    with patch.object(a,'mounted',return_value='/dev/test'),patch.object(a,'db_open') as opening:
        try:a.dispatch({'op':'delete','name':'../../etc'});raise AssertionError('path accepted')
        except ValueError:pass
        opening.assert_not_called()
print('PASS: quota migration verification, original preservation, resize guard, deletion tombstones, busy/pool/path guards')
