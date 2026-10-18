#!/usr/bin/env python3
"""Root-only Unix-socket broker for one quota-enabled ext4 pool. No network listener."""
import ctypes
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import socketserver
import sqlite3
import subprocess

POOL = Path('/srv/linux-lab-storage/pool')
STATE = Path('/var/lib/linux-lab-storage')
SOCKET = '/run/linux-lab-storage/agent.sock'
NAME = re.compile(r'linux-lab-home-v1-[0-9a-f]{64}\Z')
IDENT = re.compile(r'[a-z0-9][a-z0-9-]{0,63}\Z')


def run(*args, timeout=120):
    return subprocess.run(args, check=True, text=True, capture_output=True, timeout=timeout).stdout.strip()


def mounted():
    mount = json.loads(run('findmnt','--json','--mountpoint',str(POOL),'-o','SOURCE,FSTYPE,OPTIONS,UUID'))['filesystems'][0]
    expected = (STATE/'pool.uuid').read_text().strip()
    if mount['fstype'] != 'ext4' or mount.get('uuid') != expected or 'prjquota' not in mount['options'].split(','):
        raise ValueError('Expected quota pool is not mounted. Storage is unavailable.')
    return mount['source']


class Dqblk(ctypes.Structure):
    _fields_ = [(x,ctypes.c_uint64) for x in ('bhard','bsoft','space','ihard','isoft','inodes','btime','itime')] + [('valid',ctypes.c_uint32)]


def usage(project):
    data = Dqblk()
    libc = ctypes.CDLL(None,use_errno=True)
    libc.quotactl.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_void_p]
    if libc.quotactl(ctypes.c_int((0x800007 << 8) | 2), mounted().encode(), project, ctypes.byref(data)) != 0:
        raise OSError(ctypes.get_errno(), 'Cannot read project quota')
    return {'used_bytes':data.space,'limit_bytes':data.bhard*1024,'used_inodes':data.inodes}


def db_open():
    db=sqlite3.connect(STATE/'homes.db')
    db.row_factory=sqlite3.Row
    db.execute('''CREATE TABLE IF NOT EXISTS homes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, labels TEXT NOT NULL,
        limit_mb INTEGER NOT NULL, state TEXT NOT NULL, copied INTEGER NOT NULL DEFAULT 0)''')
    db.commit()
    return db


def inspect_volume(name):
    result=subprocess.run(['docker','volume','inspect',name],text=True,capture_output=True,timeout=30)
    if result.returncode:
        # Distinguish absent volumes from an unavailable Docker daemon.
        names=run('docker','volume','ls','--format','{{.Name}}').splitlines()
        if name in names:
            raise ValueError('Docker volume inspection failed.')
        return None
    return json.loads(result.stdout)[0]


def unattached(name):
    for volume in (name,name+'-quota'):
        if run('docker','ps','-aq','--filter','volume='+volume):
            raise ValueError('A running or stopped lab still references this home.')


def labels_for(name, scope):
    if set(scope) != {'college_id','classroom_id','template_id'} or any(not IDENT.fullmatch(str(v)) for v in scope.values()):
        raise ValueError('Invalid home scope.')
    return {'linux-lab.storage':'home-v1','linux-lab.home':name,
            'linux-lab.college':scope['college_id'],'linux-lab.classroom':scope['classroom_id'],
            'linux-lab.template':scope['template_id']}


def verify_volume(volume, labels, quota=False):
    expected={**labels,'linux-lab.storage':'quota-v1'} if quota else labels
    if any((volume.get('Labels') or {}).get(k)!=v for k,v in expected.items()):
        raise ValueError('Volume ownership mismatch.')
    if volume.get('Driver')!='local':
        raise ValueError('Unexpected volume driver.')
    if quota:
        target=str(POOL/labels['linux-lab.home'])
        if volume.get('Options')!={'type':'none','o':'bind','device':target}:
            raise ValueError('Quota volume mount does not match the registry.')
    elif volume.get('Options'):
        raise ValueError('Cannot migrate an external volume automatically.')


def snapshot(row):
    result={'name':row['name'],'state':row['state'],'limit_mb':row['limit_mb'],'copied':bool(row['copied'])}
    if row['state']=='ready':
        result.update(usage(row['id']+10000))
    return result


def ensure(db, name, scope, limit):
    if type(limit) is not int or not 64 <= limit <= 16384:
        raise ValueError('Storage allowance must be 64–16384 MiB.')
    labels=labels_for(name,scope)
    unattached(name)
    row=db.execute('SELECT * FROM homes WHERE name=?',(name,)).fetchone()
    if row and json.loads(row['labels'])!=labels:
        raise ValueError('Registered ownership mismatch.')
    if row and row['state']=='deleting':
        raise ValueError('Deletion is incomplete. Retry deletion before starting a lab.')
    others=db.execute("SELECT COALESCE(SUM(limit_mb),0) FROM homes WHERE name!=? AND state!='deleted'",(name,)).fetchone()[0]
    fs=os.statvfs(POOL)
    # Reserve metadata/headroom and never promise more than the pool can hold.
    budget=(fs.f_blocks*fs.f_frsize*90//100)//(1024*1024)
    if others+limit > budget:
        raise ValueError('Storage pool allocation is full. Reduce allowances or expand the pool.')
    if row and row['state']=='ready' and usage(row['id']+10000)['used_bytes']>limit*1024*1024:
        raise ValueError('The home already uses more than the requested allowance. Remove files first.')
    if not row:
        db.execute("INSERT INTO homes(name,labels,limit_mb,state) VALUES (?,?,?,'preparing')",(name,json.dumps(labels,sort_keys=True),limit))
        db.commit()
        row=db.execute('SELECT * FROM homes WHERE name=?',(name,)).fetchone()
    target=POOL/name
    if target.is_symlink():
        raise ValueError('Home path is not a directory.')
    target.mkdir(mode=0o700,exist_ok=True)
    project=row['id']+10000
    run('chattr','-p',str(project),'+P',str(target))
    run('setquota','-P',str(project),'0',str(limit*1024),'0','100000',str(POOL))
    if usage(project)['limit_bytes'] != limit*1024*1024:
        raise ValueError('Hard quota verification failed.')
    # Reuse a successfully copied home; never resurrect an explicitly deleted one.
    if row['state']=='preparing' and not row['copied']:
        old=inspect_volume(name)
        if old:
            verify_volume(old,labels)
            source=Path(old['Mountpoint'])
            if not source.is_absolute() or not source.is_dir() or source.is_symlink():
                raise ValueError('Legacy home source is unavailable.')
            run('rsync','-aH','--numeric-ids','--no-devices','--no-specials','--',str(source)+'/',str(target)+'/',timeout=180)
            diff=run('rsync','-aHnc','--numeric-ids','--no-devices','--no-specials','--itemize-changes','--',str(source)+'/',str(target)+'/',timeout=180)
            if diff:
                raise ValueError('Copied home did not verify. Original home retained.')
            db.execute('UPDATE homes SET copied=1 WHERE name=?',(name,));db.commit()
    os.chown(target,1000,1000)
    quota_name=name+'-quota'
    volume=inspect_volume(quota_name)
    if volume:
        verify_volume(volume,labels,quota=True)
    else:
        args=['docker','volume','create','--driver','local','--opt','type=none','--opt','o=bind','--opt','device='+str(target)]
        for k,v in {**labels,'linux-lab.storage':'quota-v1'}.items():
            args.extend(['--label',k+'='+v])
        run(*args,quota_name)
    db.execute("UPDATE homes SET limit_mb=?,state='ready' WHERE name=?",(limit,name));db.commit()
    return {**snapshot(db.execute('SELECT * FROM homes WHERE name=?',(name,)).fetchone()),'volume':quota_name}


def purge(db,name):
    row=db.execute('SELECT * FROM homes WHERE name=?',(name,)).fetchone()
    if row is None:
        raise ValueError('Quota home not found.')
    unattached(name)
    labels=json.loads(row['labels'])
    volume=inspect_volume(name+'-quota')
    if volume:
        verify_volume(volume,labels,quota=True)
        run('docker','volume','rm',name+'-quota')
    # Tombstone before filesystem removal makes interrupted deletion retryable.
    db.execute("UPDATE homes SET state='deleting' WHERE name=?",(name,));db.commit()
    target=POOL/name
    if target.is_symlink():
        raise ValueError('Refusing a symlink home path.')
    if target.exists():
        shutil.rmtree(target)
    db.execute("UPDATE homes SET state='deleted',limit_mb=0 WHERE name=?",(name,));db.commit()
    return {'deleted':True,'original_backup_retained':bool(row['copied'])}


def dispatch(message):
    mounted()  # Never operate on the root filesystem if the pool failed to mount.
    op=message.get('op')
    name=message.get('name','')
    if op not in ('list','health') and not NAME.fullmatch(name):
        raise ValueError('Invalid home name.')
    db=db_open()
    try:
        if op=='health':
            usage(10000)
            return {'status':'ok'}
        if op=='list':
            return {'homes':[snapshot(row) for row in db.execute('SELECT * FROM homes')]}
        if op=='info':
            row=db.execute('SELECT * FROM homes WHERE name=?',(name,)).fetchone()
            return snapshot(row) if row else {'state':'absent'}
        if op=='ensure':
            return ensure(db,name,message['scope'],message['limit_mb'])
        if op=='delete':
            return purge(db,name)
        raise ValueError('Unsupported storage operation.')
    finally:
        db.close()


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(200)
        try:
            raw=self.rfile.readline(16385)
            if len(raw)>16384 or not raw.endswith(b'\n'):
                raise ValueError('Invalid storage request.')
            result=dispatch(json.loads(raw))
            response={'ok':True,'result':result}
        except ValueError as exc:
            response={'ok':False,'error':str(exc)}
        except Exception as exc:
            print('Storage operation failed:',repr(exc),flush=True)
            response={'ok':False,'error':'Storage operation failed; check linux-lab-storage service logs. Original migration source is retained.'}
        self.wfile.write(json.dumps(response).encode()+b'\n')


if __name__=='__main__':
    if os.geteuid()!=0:
        raise SystemExit('The storage agent must run as root on the Docker host.')
    if not shutil.rmtree.avoids_symlink_attacks:
        raise SystemExit('This host Python lacks safe directory deletion support.')
    STATE.mkdir(mode=0o700,parents=True,exist_ok=True)
    lock=open(STATE/'agent.lock','w')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    mounted()
    Path(SOCKET).parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    Path(SOCKET).unlink(missing_ok=True)
    os.umask(0o077)
    with socketserver.UnixStreamServer(SOCKET,Handler) as server:
        server.serve_forever()
