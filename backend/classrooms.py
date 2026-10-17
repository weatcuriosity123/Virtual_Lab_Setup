"""Classroom configuration and local operator CLI; no public management API."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3


def connect():
    path = Path(os.getenv('SESSION_DB', '/data/sessions.db'))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def init_catalog(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS colleges (
      id TEXT PRIMARY KEY, name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS lab_templates (
      id TEXT PRIMARY KEY, name TEXT NOT NULL, image TEXT NOT NULL,
      memory_mb INTEGER NOT NULL CHECK(memory_mb >= 256),
      cpu_millis INTEGER NOT NULL CHECK(cpu_millis > 0),
      shm_mb INTEGER NOT NULL CHECK(shm_mb > 0),
      home_mb INTEGER NOT NULL CHECK(home_mb > 0),
      pids INTEGER NOT NULL CHECK(pids >= 64), enabled INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS classrooms (
      id TEXT PRIMARY KEY, college_id TEXT NOT NULL REFERENCES colleges(id),
      template_id TEXT NOT NULL REFERENCES lab_templates(id), name TEXT NOT NULL,
      code_hash TEXT NOT NULL, code_salt TEXT NOT NULL,
      session_minutes INTEGER NOT NULL CHECK(session_minutes > 0),
      max_sessions INTEGER NOT NULL CHECK(max_sessions > 0),
      expires_at TEXT, enabled INTEGER NOT NULL DEFAULT 1);
    ''')
    db.execute("""CREATE TABLE IF NOT EXISTS classroom_memberships (
      classroom_id TEXT NOT NULL REFERENCES classrooms(id), email TEXT NOT NULL,
      enabled INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(classroom_id,email))""")
    db.execute("""CREATE TABLE IF NOT EXISTS admin_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at TEXT NOT NULL,
        actor_email TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL,
        details TEXT NOT NULL)""")
    db.commit()


def code_hash(code, salt):
    return hashlib.pbkdf2_hmac('sha256', code.encode(), bytes.fromhex(salt), 200_000).hex()


def matches(code, row):
    return hmac.compare_digest(code_hash(code, row['code_salt']), row['code_hash'])


def resolve_classroom(db, code):
    # Small pilot catalog: salted hashes require a scan. Move to identity-based
    # enrollment/admission and rate limiting before large public deployment.
    rows = db.execute('''SELECT c.*, g.name AS college_name, g.enabled AS college_enabled,
      t.name AS template_name, t.enabled AS template_enabled, t.image,
      t.memory_mb, t.cpu_millis, t.shm_mb, t.home_mb, t.pids
      FROM classrooms c JOIN colleges g ON g.id=c.college_id
      JOIN lab_templates t ON t.id=c.template_id''').fetchall()
    for row in rows:
        if matches(code, row):
            if not (row['enabled'] and row['college_enabled'] and row['template_enabled']):
                return None
            if row['expires_at'] and datetime.now(timezone.utc) >= datetime.fromisoformat(row['expires_at']):
                return None
            return dict(row)
    return None


def new_code(db, code, exclude=None):
    if not 6 <= len(code) <= 200 or code != code.strip():
        raise ValueError('Code must contain 6–200 characters with no surrounding spaces.')
    legacy = os.getenv('CLASS_ACCESS_CODE', '')
    if legacy and hmac.compare_digest(code.encode(), legacy.encode()):
        raise ValueError('Choose a code different from CLASS_ACCESS_CODE.')
    for row in db.execute('SELECT * FROM classrooms'):
        if row['id'] != exclude and matches(code, row):
            raise ValueError('This code is already assigned to another classroom.')
    salt = secrets.token_hex(16)
    return code_hash(code, salt), salt


def identifier(value):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', value):
        raise argparse.ArgumentTypeError('Use 1–64 lowercase letters, digits or hyphens.')
    return value


def positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError('Must be positive.')
    return number


def expiry(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError()
        if parsed <= datetime.now(timezone.utc):
            raise ValueError()
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError('Use a future ISO timestamp with timezone.')


def prompt_code():
    first = getpass.getpass('Classroom code (hidden): ')
    if first != getpass.getpass('Confirm classroom code: '):
        raise ValueError('Codes do not match.')
    return first


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    college = commands.add_parser('college-add')
    college.add_argument('id', type=identifier)
    college.add_argument('--name', required=True)
    template = commands.add_parser('template-add')
    template.add_argument('id', type=identifier)
    template.add_argument('--name', required=True)
    template.add_argument('--image', required=True)
    for flag, default in [('memory-mb', 768), ('cpu-millis', 750), ('shm-mb', 256), ('home-mb', 300), ('pids', 256)]:
        template.add_argument('--'+flag, type=positive, default=default)
    classroom = commands.add_parser('classroom-add')
    classroom.add_argument('id', type=identifier)
    classroom.add_argument('--college', required=True, type=identifier)
    classroom.add_argument('--template', required=True, type=identifier)
    classroom.add_argument('--name', required=True)
    classroom.add_argument('--minutes', type=positive, default=60)
    classroom.add_argument('--slots', type=positive, default=2)
    classroom.add_argument('--expires-at', type=expiry)
    rotate = commands.add_parser('code-rotate')
    rotate.add_argument('id', type=identifier)
    state = commands.add_parser('set-enabled')
    state.add_argument('kind', choices=['college', 'template', 'classroom'])
    state.add_argument('id', type=identifier)
    state.add_argument('enabled', choices=['yes', 'no'])
    member = commands.add_parser('member-add')
    member.add_argument('classroom', type=identifier)
    member.add_argument('--email', required=True)
    revoke = commands.add_parser('member-disable')
    revoke.add_argument('classroom', type=identifier)
    revoke.add_argument('--email', required=True)
    commands.add_parser('list')
    args = parser.parse_args()
    try:
        with closing(connect()) as db:
            init_catalog(db)
            if args.command == 'list':
                result = {}
                for table in ['colleges', 'lab_templates', 'classrooms', 'classroom_memberships']:
                    result[table] = [{k: row[k] for k in row.keys() if k not in ('code_hash', 'code_salt')}
                                     for row in db.execute('SELECT * FROM '+table)]
                print(json.dumps(result, indent=2))
                return
            # Serialize local operators, including code uniqueness checks.
            code = prompt_code() if args.command in ('classroom-add', 'code-rotate') else None
            db.execute('BEGIN IMMEDIATE')
            if args.command in ('member-add', 'member-disable'):
                email = args.email.strip().lower()
                if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email) or len(email)>254:
                    raise ValueError('Provide a valid student email address.')
                if args.command == 'member-add':
                    db.execute("""INSERT INTO classroom_memberships(classroom_id,email) VALUES (?,?)
                      ON CONFLICT(classroom_id,email) DO UPDATE SET enabled=1""", (args.classroom,email))
                else:
                    result=db.execute('UPDATE classroom_memberships SET enabled=0 WHERE classroom_id=? AND email=?',
                                      (args.classroom,email))
                    if result.rowcount != 1:
                        raise ValueError('Membership not found.')
            elif args.command == 'college-add':
                db.execute('INSERT INTO colleges(id,name) VALUES (?,?)', (args.id, args.name))
            elif args.command == 'template-add':
                if not args.image or any(ch.isspace() for ch in args.image):
                    raise ValueError('Image must be a valid local Docker image reference.')
                db.execute('''INSERT INTO lab_templates
                  (id,name,image,memory_mb,cpu_millis,shm_mb,home_mb,pids) VALUES (?,?,?,?,?,?,?,?)''',
                  (args.id,args.name,args.image,args.memory_mb,args.cpu_millis,args.shm_mb,args.home_mb,args.pids))
            elif args.command == 'classroom-add':
                digest, salt = new_code(db, code)
                db.execute('''INSERT INTO classrooms
                  (id,college_id,template_id,name,code_hash,code_salt,session_minutes,max_sessions,expires_at)
                  VALUES (?,?,?,?,?,?,?,?,?)''',
                  (args.id,args.college,args.template,args.name,digest,salt,args.minutes,args.slots,args.expires_at))
            elif args.command == 'code-rotate':
                if not db.execute('SELECT 1 FROM classrooms WHERE id=?', (args.id,)).fetchone():
                    raise ValueError('Classroom not found.')
                digest, salt = new_code(db, code, exclude=args.id)
                db.execute('UPDATE classrooms SET code_hash=?,code_salt=? WHERE id=?', (digest,salt,args.id))
            elif args.command == 'set-enabled':
                table = {'college':'colleges','template':'lab_templates','classroom':'classrooms'}[args.kind]
                result = db.execute('UPDATE '+table+' SET enabled=? WHERE id=?', (args.enabled=='yes',args.id))
                if result.rowcount != 1:
                    raise ValueError('Entry not found.')
            db.commit()
            print('Saved. Membership changes apply on the next access check; classroom settings apply to new admissions.')
    except (ValueError, sqlite3.Error) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
