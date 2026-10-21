"""Opt-in, single-host homes. Deletion is restricted to the confirmed admin endpoint."""
import hashlib
import json
import os
import socket
from contextlib import closing
from datetime import datetime, timezone
import classrooms
import plans
from types import SimpleNamespace

from docker.errors import NotFound
from fastapi import HTTPException


def quota_enabled():
    mode=os.getenv('PERSISTENT_STORAGE_BACKEND','legacy')
    if mode not in ('legacy','quota'):
        raise HTTPException(503,'Invalid persistent storage backend configuration.')
    return mode == 'quota'


def quota_rpc(op, **fields):
    try:
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
            sock.settimeout(200 if op=='ensure' else 15)
            sock.connect('/run/linux-lab-storage/agent.sock')
            sock.sendall(json.dumps({'op':op,**fields}).encode()+b'\n')
            with sock.makefile('rb') as stream:
                raw=stream.readline(2*1024*1024)
            if not raw.endswith(b'\n'):
                raise ValueError('Incomplete storage response')
            result=json.loads(raw)
        if not result.get('ok'):
            raise HTTPException(409,result.get('error','Storage request failed.'))
        return result['result']
    except HTTPException:
        raise
    except (OSError,ValueError):
        raise HTTPException(503,'Saved storage is unavailable. No temporary replacement was created. Contact an administrator.')


def home_name(context, actor):
    # Bind to verified subject AND email; changing identity requires explicit migration.
    scope = [context['college_id'], context['classroom_id'], context['template_id'],
             actor.subject, actor.email.lower()]
    digest = hashlib.sha256(json.dumps(scope, separators=(',', ':')).encode()).hexdigest()
    return 'linux-lab-home-v1-' + digest


def subscription_active(classroom_id, email):
    with closing(classrooms.connect()) as db:
        row = db.execute("""SELECT e.persistent, e.expires_at FROM storage_entitlements e
            JOIN classroom_memberships m ON m.classroom_id=e.classroom_id AND m.email=e.email
            WHERE e.classroom_id=? AND e.email=? AND m.enabled=1""",
            (classroom_id, email.lower())).fetchone()
    if not row or not row['persistent']:
        return False
    if not row['expires_at']:
        return True
    expiry = datetime.fromisoformat(row['expires_at'])
    return expiry.tzinfo is not None and expiry > datetime.now(timezone.utc)


def home_options(client, context, actor, auth_mode):
    enabled = {x.strip() for x in os.getenv('PERSISTENT_HOME_TEMPLATES', '').split(',') if x.strip()}
    if context['template_id'] not in enabled:
        return {'tmpfs': {'/config': f"rw,size={context['home_mb']}m,mode=1777"}}
    if auth_mode != 'cloudflare' or not actor or not all(
        context.get(key) for key in ('college_id', 'classroom_id', 'template_id')
    ):
        raise HTTPException(403, 'Persistent homes require verified classroom membership.')
    if not subscription_active(context["classroom_id"], actor.email):
        return {"tmpfs": {"/config": f"rw,size={context['home_mb']}m,mode=1777"}}
    name = home_name(context, actor)
    with closing(classrooms.connect()) as db:
        db.execute('BEGIN IMMEDIATE')
        if plans.get(db,context['college_id']) and not quota_enabled():
            raise HTTPException(503,'College plans require the quota backend for persistent storage.')
        db.execute("""INSERT OR IGNORE INTO student_homes
            (name,college_id,classroom_id,template_id,owner_subject,owner_email) VALUES (?,?,?,?,?,?)""",
            (name,context['college_id'],context['classroom_id'],context['template_id'],actor.subject,actor.email.lower()))
        entitlement=db.execute('SELECT limit_mb FROM storage_entitlements WHERE classroom_id=? AND email=?',
                               (context['classroom_id'],actor.email.lower())).fetchone()
        plans.reserve_storage(db,context['classroom_id'],[actor.email.lower()],entitlement['limit_mb'])
        db.commit()
    if quota_enabled():
        result=quota_rpc('ensure',name=name,
                         scope={key:context[key] for key in ('college_id','classroom_id','template_id')},
                         limit_mb=entitlement['limit_mb'])
        if result.get('volume') != name+'-quota':
            raise HTTPException(503,'Unexpected saved-home mount.')
        return {'volumes': {result['volume']: {'bind':'/config','mode':'rw'}}}
    # Include stopped/orphaned containers: never share an editor profile, even if DB cleanup failed.
    if client.containers.list(all=True, filters={'volume': name}):
        raise HTTPException(409, 'Your saved home is attached to another lab. Resume or end that lab first; contact an admin if it has ended.')
    labels = {'linux-lab.storage': 'home-v1', 'linux-lab.home': name,
              'linux-lab.college': context['college_id'],
              'linux-lab.classroom': context['classroom_id'],
              'linux-lab.template': context['template_id']}
    try:
        volume = client.volumes.get(name)
    except NotFound:
        volume = client.volumes.create(name=name, labels=labels)
    if any((volume.attrs.get('Labels') or {}).get(k) != v for k, v in labels.items()):
        raise HTTPException(409, 'Saved-home ownership metadata does not match. Contact an admin.')
    return {'volumes': {name: {'bind': '/config', 'mode': 'rw'}}}


def known_homes(db, college_ids=None):
    """Resolve hashed home names from server-owned identity/session history."""
    result = {}
    sql = """SELECT DISTINCT college_id,classroom_id,template_id,owner_subject,owner_email
        FROM sessions WHERE college_id IS NOT NULL AND classroom_id IS NOT NULL
        AND template_id IS NOT NULL AND owner_subject IS NOT NULL AND owner_email IS NOT NULL"""
    params = []
    if college_ids is not None:
        if not college_ids:
            return result
        sql += ' AND college_id IN (' + ','.join('?' for _ in college_ids) + ')'
        params = college_ids
    registered = "SELECT college_id,classroom_id,template_id,owner_subject,owner_email FROM student_homes"
    if college_ids is not None:
        registered += " WHERE college_id IN (" + ",".join("?" for _ in college_ids) + ")"
    for row in list(db.execute(sql,params)) + list(db.execute(registered,params)):
        context = dict(row)
        name = home_name(context, SimpleNamespace(subject=row['owner_subject'],email=row['owner_email']))
        result[name] = {'name':name,'email':row['owner_email'].lower(),
                        'college_id':row['college_id'],'classroom_id':row['classroom_id'],
                        'template_id':row['template_id']}
    return result


def validate_home_volume(volume, home):
    expected = {'linux-lab.storage':'home-v1','linux-lab.home':home['name'],
                'linux-lab.college':home['college_id'],'linux-lab.classroom':home['classroom_id'],
                'linux-lab.template':home['template_id']}
    if any((volume.attrs.get('Labels') or {}).get(k)!=v for k,v in expected.items()):
        raise HTTPException(409, 'Saved-home ownership metadata does not match. Nothing was deleted.')
    # External/bind/block volumes need a storage-specific purge; removing their
    # Docker record alone would NOT delete the underlying files.
    if volume.attrs.get('Driver') != 'local' or volume.attrs.get('Options'):
        raise HTTPException(409, 'This storage type requires a host-managed purge. Nothing was deleted.')
