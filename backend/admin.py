"""Platform administration; all routes require a verified administrator."""
from contextlib import closing
import sqlite3
import re
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


class State(BaseModel):
    enabled: bool


def mutation_guard(request: Request):
    # Custom header prevents cross-site form submissions. No cross-origin CORS is enabled.
    if request.method != 'GET' and request.headers.get('X-Lab-Admin') != '1':
        raise HTTPException(403, 'Use the admin dashboard to make changes.')


def make_router(lab):
    router = APIRouter(prefix='/admin', dependencies=[Depends(identity.require_admin), Depends(mutation_guard)])

    def write(operation):
        try:
            with closing(classrooms.connect()) as db:
                db.execute('BEGIN IMMEDIATE')
                operation(db)
                db.commit()
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'Duplicate ID or missing college, template, or classroom.')
        return {'status': 'saved'}

    def exists(db, table, key):
        if not db.execute('SELECT 1 FROM '+table+' WHERE id=?', (key,)).fetchone():
            raise HTTPException(404, 'Entry not found.')

    @router.get('/overview')
    def overview():
        with closing(classrooms.connect()) as db:
            result = {}
            for table in ['colleges', 'lab_templates', 'classrooms', 'classroom_memberships']:
                result[table] = [{k: row[k] for k in row.keys() if k not in ('code_hash','code_salt')}
                                 for row in db.execute('SELECT * FROM '+table)]
            result['sessions'] = [dict(row) for row in db.execute("""SELECT token,owner_email,
                college_name,classroom_name,status,expires_at FROM sessions
                WHERE status IN ('active','starting') ORDER BY expires_at""")]
            has_feedback = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='feedback'").fetchone()
            result['feedback'] = [dict(row) for row in db.execute('''SELECT f.rating,f.worked,f.comments,
                f.submitted_at,s.classroom_name FROM feedback f LEFT JOIN sessions s
                ON s.token=f.session_token ORDER BY f.submitted_at DESC LIMIT 100''')] if has_feedback else []
            result['capacity'] = lab.MAX_SESSIONS
            return result

    @router.post('/colleges')
    def college(body: Entry):
        return write(lambda db: db.execute('INSERT INTO colleges(id,name) VALUES (?,?)', (body.id,body.name)))

    @router.post('/classrooms')
    def classroom(body: Classroom):
        def operation(db):
            digest,salt = classrooms.new_code(db,body.code)
            db.execute('''INSERT INTO classrooms(id,name,college_id,template_id,code_hash,code_salt,session_minutes,max_sessions)
                VALUES (?,?,?,?,?,?,?,?)''', (body.id,body.name,body.college_id,body.template_id,digest,salt,body.session_minutes,body.max_sessions))
        return write(operation)

    @router.post('/classrooms/{key}/code')
    def rotate(key: str, body: Code):
        def operation(db):
            exists(db,'classrooms',key)
            digest,salt = classrooms.new_code(db,body.code,exclude=key)
            db.execute('UPDATE classrooms SET code_hash=?,code_salt=? WHERE id=?',(digest,salt,key))
        return write(operation)

    @router.post('/classrooms/{key}/members')
    def member(key: str, body: Member):
        def operation(db):
            exists(db,'classrooms',key)
            db.execute('''INSERT INTO classroom_memberships(classroom_id,email,enabled) VALUES (?,?,?)
                ON CONFLICT(classroom_id,email) DO UPDATE SET enabled=excluded.enabled''',
                (key,body.email.lower(),body.enabled))
        return write(operation)

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
            exists(db, 'classrooms', key)
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
        write(operation)
        return {'status': 'saved', **counts}

    @router.post('/{kind}/{key}/enabled')
    def enabled(kind: str, key: str, body: State):
        table = {'colleges':'colleges','classrooms':'classrooms'}.get(kind)
        if table is None:
            raise HTTPException(404, 'Unsupported entry type.')
        def operation(db):
            exists(db,table,key)
            db.execute('UPDATE '+table+' SET enabled=? WHERE id=?',(body.enabled,key))
        return write(operation)

    @router.post('/sessions/{token}/terminate')
    async def terminate(token: str):
        async with lab.creation_lock:
            with closing(classrooms.connect()) as db:
                row = db.execute('SELECT status FROM sessions WHERE token=?',(token,)).fetchone()
                if row is None:
                    raise HTTPException(404,'Session not found.')
            if row['status'] in ('active','starting'):
                lab.delete_session(token)
        return {'status':'ended'}

    return router
