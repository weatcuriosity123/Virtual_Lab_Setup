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
from pydantic import BaseModel, Field, field_validator, ValidationError
from typing import Literal
import classrooms
import identity
import storage
import plans
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


class ApprovalRequest(BaseModel):
    kind: Literal['storage', 'enrollment', 'classroom_create', 'classroom_enable', 'college_plan']
    target: str = Field(min_length=1, max_length=64)
    payload: dict
    reason: str = Field(min_length=1, max_length=2000, pattern=r'.*\S.*')


class ClassroomProposal(Entry):
    template_id: str
    session_minutes: int = Field(default=60, ge=1, le=480)
    max_sessions: int = Field(default=1, ge=1, le=1000)


class Review(BaseModel):
    approve: bool
    note: str = Field(default='', max_length=2000)
    code: str | None = Field(default=None, min_length=6, max_length=200)


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
        if action.startswith(('college.', 'colleges.', 'college_admin.', 'approval.')):
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
                if action:
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
            result['requests'] = rows("""SELECT * FROM admin_requests WHERE {scope}
                ORDER BY CASE WHEN status='pending' THEN 0 ELSE 1 END, id DESC""", 'college_id')
            for item in result['requests']:
                item['payload'] = json.loads(item['payload'])
                item.pop('baseline', None)
            result['plans'] = []
            for college in result['colleges']:
                plan = plans.get(db,college['id'])
                item = {'college_id':college['id'], 'configured':bool(plan), 'storage_reserved_mb':plans.storage_total(db,college['id'])}
                if plan:
                    item.update(config=plan.model_dump(),usage=plans.usage(db,college['id'],plan,datetime.now(timezone.utc)))
                result['plans'].append(item)
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
        identity.require_platform_admin()
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
        identity.require_platform_admin()
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
        if body.enabled:
            identity.require_platform_admin()
        def operation(db):
            classroom_scope(db,key)
            db.execute('''INSERT INTO classroom_memberships(classroom_id,email,enabled) VALUES (?,?,?)
                ON CONFLICT(classroom_id,email) DO UPDATE SET enabled=excluded.enabled''',
                (key,body.email.lower(),body.enabled))
        return write(operation, 'membership.enabled' if body.enabled else 'membership.disabled', key, {'email': body.email.lower()})

    @router.post('/classrooms/{key}/members/bulk')
    def bulk_members(key: str, body: BulkMembers):
        identity.require_platform_admin()
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

    def apply_storage(db, key, body):
        emails = [x.lower() for x in re.split(r'[\s,;]+', body.emails.strip()) if x]
        if not 1 <= len(emails) <= 500 or any(len(x)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',x) for x in emails):
            raise HTTPException(400, 'Enter 1–500 valid student emails. Nothing was saved.')
        emails = list(dict.fromkeys(emails))
        expiry = body.expires_at.isoformat() if body.persistent and body.expires_at else None
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
        if body.persistent:
            plans.reserve_storage(db,key,emails,body.limit_mb)
        return emails, expiry

    @router.post('/classrooms/{key}/storage')
    def storage_subscription(key: str, body: StorageSubscription):
        identity.require_platform_admin()
        result = {}
        def operation(db):
            emails, expiry = apply_storage(db, key, body)
            result.update(emails=emails, persistent=body.persistent, expires_at=expiry, limit_mb=body.limit_mb)
        write(operation, 'membership.storage_changed', key, result)
        return {'status':'saved','students':len(result['emails'])}

    def proposal(body):
        models = {'storage': StorageSubscription, 'enrollment': BulkMembers,
                  'classroom_create': ClassroomProposal, 'classroom_enable': State, 'college_plan': plans.CollegePlan}
        model = models[body.kind]
        if set(body.payload) - set(model.model_fields):
            raise HTTPException(400, 'Unexpected request fields.')
        try:
            value = model.model_validate(body.payload)
        except ValidationError:
            raise HTTPException(400, 'Invalid request values. Check emails, limits and future expiry.')
        if body.kind in ('storage', 'enrollment'):
            emails = [x.lower() for x in re.split(r'[\s,;]+', value.emails.strip()) if x]
            if not 1 <= len(emails) <= 500 or any(len(x)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', x) for x in emails):
                raise HTTPException(400, 'Enter 1–500 valid student emails.')
            value.emails = '\n'.join(dict.fromkeys(emails))
        if body.kind == 'classroom_enable' and not value.enabled:
            raise HTTPException(400, 'Disabling a classroom does not require approval.')
        return value

    def request_baseline(db, kind, target, value):
        def row(sql, args):
            item = db.execute(sql,args).fetchone()
            return dict(item) if item else None
        if kind == 'college_plan':
            return json.dumps(row('SELECT * FROM college_plans WHERE college_id=?',(target,)),sort_keys=True)
        if kind == 'classroom_create':
            state = {'college':row('SELECT * FROM colleges WHERE id=?',(target,)),
                     'template':row('SELECT * FROM lab_templates WHERE id=?',(value.template_id,)),
                     'existing':row('SELECT id FROM classrooms WHERE id=?',(value.id,))}
        else:
            classroom = row('SELECT id,college_id,template_id,enabled,session_minutes,max_sessions FROM classrooms WHERE id=?',(target,))
            state = {'classroom':classroom}
            if classroom:
                state['template'] = row('SELECT * FROM lab_templates WHERE id=?',(classroom['template_id'],))
            if kind in ('storage', 'enrollment'):
                state['members'] = [row('SELECT * FROM classroom_memberships WHERE classroom_id=? AND email=?',(target,email)) for email in value.emails.splitlines()]
            if kind == 'storage':
                state['storage'] = [row('SELECT * FROM storage_entitlements WHERE classroom_id=? AND email=?',(target,email)) for email in value.emails.splitlines()]
        return json.dumps(state, sort_keys=True)

    @router.post('/colleges/{key}/plan')
    def save_plan(key: str, body: plans.CollegePlan):
        identity.require_platform_admin()
        return write(lambda db: plans.save(db,key,body), 'college.plan_changed', key, body.model_dump())

    @router.post('/requests')
    def create_request(body: ApprovalRequest):
        value = proposal(body)
        result = {}
        with closing(classrooms.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            if body.kind in ('classroom_create','college_plan'):
                identity.require_college_admin(db, body.target)
                exists(db, 'colleges', body.target)
                if body.kind == 'classroom_create':
                    exists(db, 'lab_templates', value.template_id)
                college_id = body.target
            else:
                classroom_scope(db, body.target)
                college_id = db.execute('SELECT college_id FROM classrooms WHERE id=?', (body.target,)).fetchone()[0]
                if body.kind == 'storage':
                    for email in value.emails.splitlines():
                        if not db.execute('SELECT 1 FROM classroom_memberships WHERE classroom_id=? AND email=?', (body.target,email)).fetchone():
                            raise HTTPException(400, 'Students must already be enrolled before requesting storage.')
            baseline = request_baseline(db,body.kind,body.target,value)
            payload = json.dumps(value.model_dump(mode='json'), sort_keys=True)
            duplicate = db.execute("SELECT id FROM admin_requests WHERE college_id=? AND kind=? AND target=? AND payload=? AND baseline=? AND status='pending'",
                                   (college_id,body.kind,body.target,payload,baseline)).fetchone()
            if duplicate:
                return {'status':'pending','id':duplicate[0]}
            if db.execute("SELECT count(*) FROM admin_requests WHERE college_id=? AND status='pending'", (college_id,)).fetchone()[0] >= 100:
                raise HTTPException(409, 'This college already has 100 pending requests. Ask the portal admin to review them.')
            cursor = db.execute("""INSERT INTO admin_requests(college_id,kind,target,payload,baseline,reason,requested_by,requested_at)
                VALUES (?,?,?,?,?,?,?,?)""", (college_id,body.kind,body.target,payload,baseline,body.reason.strip(),identity.actor().email,datetime.now(timezone.utc).isoformat()))
            result = {'status':'pending','id':cursor.lastrowid}
            record(db, 'approval.requested', college_id, {'request_id':result['id'],'kind':body.kind,'target':body.target})
            db.commit()
        return result

    @router.post('/requests/{request_id}/review')
    def review_request(request_id: int, body: Review):
        identity.require_platform_admin()
        def operation(db):
            row = db.execute('SELECT * FROM admin_requests WHERE id=?', (request_id,)).fetchone()
            if row is None:
                raise HTTPException(404, 'Request not found.')
            if row['status'] != 'pending':
                raise HTTPException(409, 'This request has already been reviewed.')
            if body.approve:
                value = proposal(ApprovalRequest(kind=row['kind'], target=row['target'], payload=json.loads(row['payload']), reason=row['reason']))
                key = row['target']
                if request_baseline(db,row['kind'],key,value) != row['baseline']:
                    raise HTTPException(409, 'Access or resource settings changed since this request. Reject it and submit a fresh request.')
                if row['kind'] == 'college_plan':
                    plans.save(db,key,value)
                elif row['kind'] == 'classroom_create':
                    if not body.code:
                        raise HTTPException(400, 'Set a classroom code when approving this request.')
                    exists(db, 'colleges', key)
                    exists(db, 'lab_templates', value.template_id)
                    digest,salt = classrooms.new_code(db,body.code)
                    db.execute("""INSERT INTO classrooms(id,name,college_id,template_id,code_hash,code_salt,session_minutes,max_sessions)
                        VALUES (?,?,?,?,?,?,?,?)""", (value.id,value.name,key,value.template_id,digest,salt,value.session_minutes,value.max_sessions))
                else:
                    scope = db.execute('SELECT college_id FROM classrooms WHERE id=?', (key,)).fetchone()
                    if not scope or scope[0] != row['college_id']:
                        raise HTTPException(409, 'Classroom scope changed. Reject this request and submit a new one.')
                    if row['kind'] == 'storage':
                        apply_storage(db,key,value)
                    elif row['kind'] == 'enrollment':
                        for email in value.emails.splitlines():
                            db.execute("""INSERT INTO classroom_memberships(classroom_id,email,enabled) VALUES (?,?,1)
                                ON CONFLICT(classroom_id,email) DO UPDATE SET enabled=1""", (key,email))
                    elif row['kind'] == 'classroom_enable':
                        db.execute('UPDATE classrooms SET enabled=1 WHERE id=?', (key,))
            status = 'approved' if body.approve else 'rejected'
            db.execute('UPDATE admin_requests SET status=?, reviewed_by=?, reviewed_at=?, review_note=? WHERE id=?',
                       (status,identity.actor().email,datetime.now(timezone.utc).isoformat(),body.note,request_id))
            record(db, 'approval.'+status, row['college_id'], {'request_id':request_id,'kind':row['kind'],'target':row['target'],'note':body.note})
        # Change, decision and audit records commit together, serialized against other reviews.
        return write(operation, None, str(request_id))

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
                if body.enabled:
                    identity.require_platform_admin()
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
