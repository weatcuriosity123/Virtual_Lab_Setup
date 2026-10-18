"""Platform administration; all routes require a verified administrator."""
from contextlib import closing
import sqlite3
import re
import json
import os
import disk_guard
import network_guard
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
import classrooms
import identity
import storage
from docker.errors import APIError, NotFound


class Entry(BaseModel):
    id: str = Field(pattern=r'^[a-z0-9][a-z0-9-]{0,63}$')
    name: str = Field(min_length=1, max_length=120, pattern=r'.*\S.*')


    @field_validator('id', mode='before')
    @classmethod
    def normalize_id(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class Classroom(Entry):
    college_id: str
    template_id: str
    code: str = Field(min_length=6, max_length=200)
    session_minutes: int = Field(default=60, ge=1, le=480)
    max_sessions: int = Field(default=2, ge=1, le=1000)


class Code(BaseModel):
    code: str = Field(min_length=6, max_length=200)


class Member(BaseModel):
    email: str = Field(max_length=254, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    enabled: bool = True


class BulkMembers(BaseModel):
    emails: str = Field(min_length=1, max_length=130000)


class StorageSubscription(BulkMembers):
    persistent: bool
    limit_mb: int = Field(default=1024, ge=64, le=16384)
    expires_at: datetime | None = None

    @field_validator('expires_at')
    @classmethod
    def validate_expiry(cls, value):
        if value is not None and (value.tzinfo is None or value <= datetime.now(timezone.utc)):
            raise ValueError('Use a future expiry with a timezone, or leave blank.')
        return value.astimezone(timezone.utc) if value else None


class DeleteHome(BaseModel):
    name: str = Field(pattern=r'^linux-lab-home-v1-[0-9a-f]{64}$')
    confirmation: str = Field(max_length=270)


class State(BaseModel):
    enabled: bool


def mutation_guard(request: Request):
    # Custom header prevents cross-site form submissions. No cross-origin CORS is enabled.
    if request.method != 'GET' and request.headers.get('X-Lab-Admin') != '1':
        raise HTTPException(403, 'Use the admin dashboard to make changes.')


def make_router(lab):
    router = APIRouter(prefix='/admin', dependencies=[Depends(identity.require_admin), Depends(mutation_guard)])

    def record(db, action, target, details):
        college_id = None
        if action.startswith(('college.', 'colleges.', 'college_admin.')):
            college_id = target
        elif action.startswith(('classroom.', 'classrooms.', 'membership.')):
            row = db.execute('SELECT college_id FROM classrooms WHERE id=?', (target,)).fetchone()
            college_id = row[0] if row else None
        elif action.startswith('session.'):
            row = db.execute('SELECT college_id FROM sessions WHERE token=?', (target,)).fetchone()
            college_id = row[0] if row else None
        db.execute('INSERT INTO admin_events(occurred_at,actor_email,action,target,details,college_id) VALUES (?,?,?,?,?,?)',
                   (datetime.now(timezone.utc).isoformat(), identity.actor().email,
                    action, target, json.dumps(details or {}, sort_keys=True), college_id))

    def write(operation, action, target, details=None):
        try:
            with closing(classrooms.connect()) as db:
                db.execute('BEGIN IMMEDIATE')
                operation(db)
                record(db, action, target, details)
                db.commit()
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'Duplicate ID or missing college, template, or classroom.')
        return {'status': 'saved'}

    def exists(db, table, key):
        if not db.execute('SELECT 1 FROM '+table+' WHERE id=?', (key,)).fetchone():
            raise HTTPException(404, 'Entry not found.')

    def classroom_scope(db, key):
        row = db.execute('SELECT college_id FROM classrooms WHERE id=?', (key,)).fetchone()
        if row is None:
            raise HTTPException(404, 'Classroom not found.')
        identity.require_college_admin(db, row['college_id'])

    @router.get('/system-health')
    def system_health():
        # Guard before any host-wide inspection: never expose this to college admins.
        identity.require_platform_admin()
        checks = []
        def check(name, operation):
            try:
                detail = operation()
                checks.append({'name': name, 'status': 'OK', 'detail': detail})
            except Exception:
                # Docker/socket exception messages can contain internal paths or credentials.
                checks.append({'name': name, 'status': 'UNAVAILABLE',
                               'detail': 'Check the host service and its logs.'})
        def docker_health():
            if not lab.docker_client.ping():
                raise RuntimeError('Docker unavailable')
            return 'Docker API responds.'
        def proxy_health():
            proxy = lab.docker_client.containers.get(lab.PROXY_CONTAINER)
            if proxy.status != 'running':
                raise RuntimeError('Proxy not running')
            return 'Proxy container is running; public connectivity is not tested.'
        check('Docker', docker_health)
        check('Desktop proxy', proxy_health)
        if storage.quota_enabled():
            check('Saved storage', lambda: (storage.quota_rpc('health'), 'Quota service responds.')[1])
        else:
            checks.append({'name': 'Saved storage', 'status': 'NOT ENABLED', 'detail': 'Quota backend is not enabled.'})
        if os.getenv('LAB_NETWORK_ISOLATION', 'off') != 'off' or lab.DOCKER_NETWORK == 'linux-lab-students':
            check('Network isolation', lambda: (network_guard.container_options(lab.DOCKER_NETWORK), 'Guard checks passed.')[1])
        else:
            checks.append({'name': 'Network isolation', 'status': 'NOT ENABLED', 'detail': 'Admission guard is not enabled.'})
        checks.extend(disk_guard.snapshot(lab.SESSION_DB))
        return {'checked_at': datetime.now(timezone.utc).isoformat(), 'checks': checks}

    @router.get('/overview')
    def overview():
        with closing(classrooms.connect()) as db:
            platform = identity.is_platform_admin()
            ids = identity.admin_colleges(db)
            if not platform and not ids:
                raise HTTPException(403, 'Administrator access required.')
            def scope(column):
                return ('1=1', []) if platform else (column+' IN ('+','.join('?' for _ in ids)+')', ids)
            def rows(sql, column):
                condition, params = scope(column)
                return [dict(row) for row in db.execute(sql.replace('{scope}',condition), params)]
            result = {'platform_admin': platform}
            result['colleges'] = rows('SELECT * FROM colleges WHERE {scope}', 'id')
            result['classrooms'] = rows('''SELECT id,college_id,template_id,name,session_minutes,max_sessions,
                expires_at,enabled FROM classrooms WHERE {scope}''', 'college_id')
            result['lab_templates'] = [dict(row) for row in db.execute(
                'SELECT * FROM lab_templates' if platform else 'SELECT id,name,enabled FROM lab_templates')]
            result['classroom_memberships'] = rows('''SELECT m.* FROM classroom_memberships m
                JOIN classrooms c ON c.id=m.classroom_id WHERE {scope}''','c.college_id')
            result['storage_entitlements'] = rows('''SELECT e.* FROM storage_entitlements e
                JOIN classrooms c ON c.id=e.classroom_id WHERE {scope}''', 'c.college_id')
            result['persistent_home_templates'] = [x.strip() for x in os.getenv('PERSISTENT_HOME_TEMPLATES','').split(',') if x.strip()]
            result['sessions'] = rows('''SELECT token,owner_email,college_name,classroom_name,status,expires_at
                FROM sessions WHERE status IN ('active','starting') AND {scope} ORDER BY expires_at''','college_id')
            has_feedback = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='feedback'").fetchone()
            result['feedback'] = rows('''SELECT f.rating,f.worked,f.comments,f.submitted_at,s.classroom_name
                FROM feedback f LEFT JOIN sessions s ON s.token=f.session_token
                WHERE {scope} ORDER BY f.submitted_at DESC LIMIT 100''', 's.college_id') if has_feedback else []
            result['activity'] = rows('SELECT * FROM admin_events WHERE {scope} ORDER BY id DESC LIMIT 100','college_id')
            result['college_admins'] = [dict(row) for row in db.execute('SELECT * FROM college_admins')] if platform else []
            result['quota_backend'] = storage.quota_enabled()
            result['capacity'] = lab.MAX_SESSIONS
            return result

    @router.get('/saved-homes')
    def saved_homes():
        with closing(classrooms.connect()) as db:
            homes = storage.known_homes(db, None if identity.is_platform_admin() else identity.admin_colleges(db))
        result = []
        quota_rows = {r['name']:r for r in storage.quota_rpc('list')['homes']} if storage.quota_enabled() else {}
        for name, info in quota_rows.items():
            if name not in homes or info['state']=='deleted':
                continue
            attached=len(lab.docker_client.containers.list(all=True,filters={'volume':name+'-quota'}))
            attached+=len(lab.docker_client.containers.list(all=True,filters={'volume':name}))
            result.append({**homes[name],**info,'attached':attached,'deletable':attached==0,'backend':'quota'})
        try:
            volumes = lab.docker_client.volumes.list(filters={'label':'linux-lab.storage=home-v1'})
            for volume in volumes:
                home = homes.get(volume.name)
                if home is None or volume.name in quota_rows:
                    continue
                try:
                    storage.validate_home_volume(volume,home)
                except HTTPException:
                    result.append({**home,'attached':None,'deletable':False})
                    continue
                attached = len(lab.docker_client.containers.list(all=True,filters={'volume':home['name']}))
                result.append({**home,'attached':attached,'deletable':attached==0,'backend':'legacy'})
        except APIError:
            raise HTTPException(503,'Could not inspect saved homes. Try again later.')
        return {'homes':result}

    @router.post('/saved-homes/delete')
    async def delete_home(body: DeleteHome):
        async with lab.creation_lock:
            with closing(classrooms.connect()) as db:
                home = storage.known_homes(db, None if identity.is_platform_admin() else identity.admin_colleges(db)).get(body.name)
                if home is None:
                    raise HTTPException(404,'Saved home not found in your colleges.')
                classroom_scope(db,home['classroom_id'])
            if body.confirmation != 'DELETE ' + home['email']:
                raise HTTPException(400,'Type DELETE followed by the exact student email to confirm.')
            if storage.quota_enabled() and storage.quota_rpc('info',name=body.name)['state']!='absent':
                details={'email':home['email'],'home':body.name,'template_id':home['template_id']}
                write(lambda db: classroom_scope(db,home['classroom_id']),
                      'membership.home_delete_requested',home['classroom_id'],details)
                try:
                    result=storage.quota_rpc('delete',name=body.name)
                except HTTPException:
                    write(lambda db: None,'membership.home_delete_failed',home['classroom_id'],details)
                    raise
                write(lambda db: None,'membership.home_deleted',home['classroom_id'],details)
                return {'status':'deleted','name':body.name,**result}
            try:
                volume = lab.docker_client.volumes.get(body.name)
            except NotFound:
                raise HTTPException(404,'Saved home no longer exists.')
            storage.validate_home_volume(volume,home)
            if lab.docker_client.containers.list(all=True,filters={'volume':body.name}):
                raise HTTPException(409,'End the lab first. A running or stopped container still references this saved home.')
            details={'email':home['email'],'home':body.name,'template_id':home['template_id']}
            # Record intent before the external side effect; failure never reports success.
            write(lambda db: classroom_scope(db,home['classroom_id']),
                  'membership.home_delete_requested',home['classroom_id'],details)
            try:
                volume.remove(force=False)
            except APIError:
                write(lambda db: None,'membership.home_delete_failed',home['classroom_id'],details)
                raise HTTPException(409,'Docker could not delete the saved home. Refresh and check for attached labs.')
            write(lambda db: None,'membership.home_deleted',home['classroom_id'],details)
        return {'status':'deleted','name':body.name}

    @router.post('/colleges/{key}/admins')
    def assign_admin(key: str, body: Member):
        identity.require_platform_admin()
        def operation(db):
            exists(db, 'colleges', key)
            db.execute('''INSERT INTO college_admins(college_id,email,enabled) VALUES (?,?,?)
                ON CONFLICT(college_id,email) DO UPDATE SET enabled=excluded.enabled''',
                (key,body.email.lower(),body.enabled))
        return write(operation, 'college_admin.granted' if body.enabled else 'college_admin.revoked', key,
                     {'email':body.email.lower()})

    @router.post('/colleges')
    def college(body: Entry):
        identity.require_platform_admin()
        return write(lambda db: db.execute('INSERT INTO colleges(id,name) VALUES (?,?)', (body.id,body.name)), 'college.created', body.id)

    @router.post('/classrooms')
    def classroom(body: Classroom):
        def operation(db):
            identity.require_college_admin(db, body.college_id)
            digest,salt = classrooms.new_code(db,body.code)
            db.execute('''INSERT INTO classrooms(id,name,college_id,template_id,code_hash,code_salt,session_minutes,max_sessions)
                VALUES (?,?,?,?,?,?,?,?)''', (body.id,body.name,body.college_id,body.template_id,digest,salt,body.session_minutes,body.max_sessions))
        return write(operation, 'classroom.created', body.id)

    @router.post('/classrooms/{key}/code')
    def rotate(key: str, body: Code):
        def operation(db):
            classroom_scope(db,key)
            digest,salt = classrooms.new_code(db,body.code,exclude=key)
            db.execute('UPDATE classrooms SET code_hash=?,code_salt=? WHERE id=?',(digest,salt,key))
        return write(operation, 'classroom.code_rotated', key)

    @router.post('/classrooms/{key}/members')
    def member(key: str, body: Member):
        def operation(db):
            classroom_scope(db,key)
            db.execute('''INSERT INTO classroom_memberships(classroom_id,email,enabled) VALUES (?,?,?)
                ON CONFLICT(classroom_id,email) DO UPDATE SET enabled=excluded.enabled''',
                (key,body.email.lower(),body.enabled))
        return write(operation, 'membership.enabled' if body.enabled else 'membership.disabled', key, {'email': body.email.lower()})

    @router.post('/classrooms/{key}/members/bulk')
    def bulk_members(key: str, body: BulkMembers):
        entries = [value.strip().lower() for value in re.split(r'[\s,;]+', body.emails) if value.strip()]
        if not entries or len(entries) > 500:
            raise HTTPException(400, 'Paste between 1 and 500 email addresses per batch.')
        invalid = [index + 1 for index, email in enumerate(entries)
                   if len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email)]
        if invalid:
            raise HTTPException(400, 'Invalid email at entry positions: '+', '.join(map(str, invalid[:20]))+'. Nothing was saved.')
        unique = list(dict.fromkeys(entries))
        counts = dict(added=0, reenabled=0, unchanged=0, duplicates=len(entries)-len(unique))
        def operation(db):
            classroom_scope(db,key)
            for email in unique:
                previous = db.execute('SELECT enabled FROM classroom_memberships WHERE classroom_id=? AND email=?',
                                      (key, email)).fetchone()
                if previous is None:
                    db.execute('INSERT INTO classroom_memberships(classroom_id,email) VALUES (?,?)', (key,email))
                    counts['added'] += 1
                elif not previous['enabled']:
                    db.execute('UPDATE classroom_memberships SET enabled=1 WHERE classroom_id=? AND email=?', (key,email))
                    counts['reenabled'] += 1
                else:
                    counts['unchanged'] += 1
        write(operation, 'membership.bulk_enrolled', key, counts)
        return {'status': 'saved', **counts}

    @router.post('/classrooms/{key}/storage')
    def storage_subscription(key: str, body: StorageSubscription):
        emails = [x.lower() for x in re.split(r'[\s,;]+', body.emails.strip()) if x]
        if not 1 <= len(emails) <= 500 or any(len(x)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',x) for x in emails):
            raise HTTPException(400, 'Enter 1–500 valid student emails. Nothing was saved.')
        emails = list(dict.fromkeys(emails))
        expiry = body.expires_at.isoformat() if body.persistent and body.expires_at else None
        def operation(db):
            classroom_scope(db,key)
            template = db.execute('SELECT template_id FROM classrooms WHERE id=?',(key,)).fetchone()[0]
            allowed = {x.strip() for x in os.getenv('PERSISTENT_HOME_TEMPLATES','').split(',') if x.strip()}
            if body.persistent and template not in allowed:
                raise HTTPException(409, 'Persistent storage is not enabled for this template on the server.')
            for email in emails:
                if not db.execute('SELECT 1 FROM classroom_memberships WHERE classroom_id=? AND email=?',(key,email)).fetchone():
                    raise HTTPException(400, 'Every email must already be enrolled in this classroom. Nothing was saved.')
                db.execute("""INSERT INTO storage_entitlements(classroom_id,email,persistent,expires_at,limit_mb)
                    VALUES (?,?,?,?,?) ON CONFLICT(classroom_id,email) DO UPDATE SET
                    persistent=excluded.persistent, expires_at=excluded.expires_at, limit_mb=excluded.limit_mb""",
                    (key,email,body.persistent,expiry,body.limit_mb))
        write(operation, 'membership.storage_changed',key,
              {'emails':emails,'persistent':body.persistent,'expires_at':expiry,'limit_mb':body.limit_mb})
        return {'status':'saved','students':len(emails)}

    @router.post('/{kind}/{key}/enabled')
    def enabled(kind: str, key: str, body: State):
        table = {'colleges':'colleges','classrooms':'classrooms'}.get(kind)
        if table is None:
            raise HTTPException(404, 'Unsupported entry type.')
        def operation(db):
            if kind == 'colleges':
                identity.require_platform_admin()
            else:
                classroom_scope(db,key)
            exists(db,table,key)
            db.execute('UPDATE '+table+' SET enabled=? WHERE id=?',(body.enabled,key))
        return write(operation, kind+'.enabled' if body.enabled else kind+'.disabled', key)

    @router.post('/sessions/{token}/terminate')
    async def terminate(token: str):
        async with lab.creation_lock:
            with closing(classrooms.connect()) as db:
                row = db.execute('SELECT status,college_id FROM sessions WHERE token=?',(token,)).fetchone()
                if row is None:
                    raise HTTPException(404,'Session not found.')
                identity.require_college_admin(db, row['college_id'])
            if row['status'] in ('active','starting'):
                write(lambda db: None, 'session.termination_requested', token)
                try:
                    lab.delete_session(token)
                except Exception:
                    write(lambda db: None, 'session.termination_failed', token)
                    raise
                write(lambda db: None, 'session.terminated', token)
        return {'status':'ended'}

    return router
