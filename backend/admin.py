"""Platform administration; all routes require a verified administrator."""
from contextlib import closing
import sqlite3
import re
import json
import os
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
import classrooms
import identity


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
    expires_at: datetime | None = None

    @field_validator('expires_at')
    @classmethod
    def validate_expiry(cls, value):
        if value is not None and (value.tzinfo is None or value <= datetime.now(timezone.utc)):
            raise ValueError('Use a future expiry with a timezone, or leave blank.')
        return value.astimezone(timezone.utc) if value else None


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
            result['capacity'] = lab.MAX_SESSIONS
            return result

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
                db.execute("""INSERT INTO storage_entitlements(classroom_id,email,persistent,expires_at)
                    VALUES (?,?,?,?) ON CONFLICT(classroom_id,email) DO UPDATE SET
                    persistent=excluded.persistent, expires_at=excluded.expires_at""",
                    (key,email,body.persistent,expiry))
        write(operation, 'membership.storage_changed',key,
              {'emails':emails,'persistent':body.persistent,'expires_at':expiry})
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
