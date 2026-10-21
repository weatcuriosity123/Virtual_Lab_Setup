"""Single-host college admission budgets. UTC ledger; college-local calendars."""
import json
import math
from contextlib import closing
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
import classrooms


class CollegePlan(BaseModel):
    seats: int = Field(ge=1, le=1000)
    monthly_hours: int = Field(ge=1, le=1000000)
    storage_mb: int = Field(ge=0, le=100000000)
    templates: list[str] = Field(min_length=1, max_length=100)
    timezone: str = 'Asia/Kolkata'
    weekdays: list[int] = Field(min_length=1, max_length=7)
    opens: str = Field(pattern=r'^([01][0-9]|2[0-3]):[0-5][0-9]$')
    closes: str = Field(pattern=r'^([01][0-9]|2[0-3]):[0-5][0-9]$')

    @field_validator('timezone')
    @classmethod
    def valid_zone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('Choose a valid IANA timezone.')
        return value

    @field_validator('weekdays')
    @classmethod
    def valid_days(cls, value):
        if any(day < 0 or day > 6 for day in value):
            raise ValueError('Weekdays must be 0 (Monday) through 6 (Sunday).')
        return sorted(set(value))

    @field_validator('templates')
    @classmethod
    def valid_templates(cls, value):
        return sorted(set(value))

    @model_validator(mode='after')
    def valid_window(self):
        if self.opens >= self.closes:
            raise ValueError('Closing time must follow opening time on the same day.')
        return self


def init(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS college_plans (
        college_id TEXT PRIMARY KEY REFERENCES colleges(id), config TEXT NOT NULL,
        updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS college_lab_usage (
        token TEXT PRIMARY KEY, college_id TEXT NOT NULL REFERENCES colleges(id),
        admitted_at TEXT NOT NULL, deadline TEXT NOT NULL, ended_at TEXT);
    CREATE INDEX IF NOT EXISTS college_usage_scope ON college_lab_usage(college_id,admitted_at);
    CREATE TABLE IF NOT EXISTS college_storage_reservations (
        classroom_id TEXT NOT NULL REFERENCES classrooms(id), email TEXT NOT NULL,
        limit_mb INTEGER NOT NULL, PRIMARY KEY(classroom_id,email));
    ''')
    # Conservative migration: include disabled/expired subscriptions because files remain.
    db.execute('''INSERT INTO college_storage_reservations(classroom_id,email,limit_mb)
        SELECT classroom_id,email,limit_mb FROM storage_entitlements WHERE 1
        ON CONFLICT(classroom_id,email) DO UPDATE SET limit_mb=MAX(limit_mb,excluded.limit_mb)''')


def get(db, college_id):
    row = db.execute('SELECT config FROM college_plans WHERE college_id=?',(college_id,)).fetchone()
    return CollegePlan.model_validate_json(row[0]) if row else None


def bounds(now, plan):
    local = now.astimezone(ZoneInfo(plan.timezone))
    start = local.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    end = (start.replace(day=28)+timedelta(days=4)).replace(day=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def storage_total(db, college_id):
    return db.execute('''SELECT COALESCE(SUM(r.limit_mb),0) FROM college_storage_reservations r
        JOIN classrooms c ON c.id=r.classroom_id WHERE c.college_id=?''',(college_id,)).fetchone()[0]


def usage(db, college_id, plan, now):
    start,end = bounds(now,plan)
    used = reserved = live = 0
    for row in db.execute('SELECT * FROM college_lab_usage WHERE college_id=? AND deadline>? AND admitted_at<?',
                          (college_id,start.isoformat(),end.isoformat())):
        began = max(datetime.fromisoformat(row['admitted_at']), start)
        deadline = min(datetime.fromisoformat(row['deadline']), end)
        stopped = datetime.fromisoformat(row['ended_at']) if row['ended_at'] else deadline
        until = min(stopped,deadline)
        used += max(0,(min(now,until)-began).total_seconds())
        reserved += max(0,(until-began).total_seconds())
        if not row['ended_at'] and deadline > now:
            live += 1
    storage = storage_total(db,college_id)
    return dict(used_seconds=math.ceil(used), reserved_seconds=math.ceil(reserved),
                active_labs=live, storage_reserved_mb=storage,
                period_start=start.isoformat(),period_end=end.isoformat())


def save(db, college_id, plan, now=None):
    now = now or datetime.now(timezone.utc)
    if not db.execute('SELECT 1 FROM colleges WHERE id=?',(college_id,)).fetchone():
        raise HTTPException(404,'College not found.')
    for template in plan.templates:
        if not db.execute('SELECT 1 FROM lab_templates WHERE id=? AND enabled=1',(template,)).fetchone():
            raise HTTPException(400,'Choose installed, enabled templates.')
    # Do not retrofit schedules or reset a monthly ledger beneath running labs.
    if db.execute("SELECT 1 FROM sessions WHERE college_id=? AND status IN ('active','starting')",(college_id,)).fetchone():
        raise HTTPException(409,'End this college’s labs before changing its plan.')
    if db.execute('SELECT 1 FROM college_lab_usage WHERE college_id=? AND ended_at IS NULL AND deadline>?',
                  (college_id,now.isoformat())).fetchone():
        raise HTTPException(409,'A lab admission is still reserved. Wait for cleanup before changing its plan.')
    previous = get(db,college_id)
    if previous and previous.timezone != plan.timezone:
        raise HTTPException(409,'The billing-calendar timezone cannot be changed after a plan is configured.')
    current = usage(db,college_id,plan,now)
    if current['storage_reserved_mb'] > plan.storage_mb:
        raise HTTPException(409,'The proposed storage cap is below existing reserved allowances.')
    if current['reserved_seconds'] > plan.monthly_hours*3600:
        raise HTTPException(409,'The proposed monthly cap is below this month’s consumed/reserved time.')
    db.execute('''INSERT INTO college_plans(college_id,config,updated_at) VALUES (?,?,?)
        ON CONFLICT(college_id) DO UPDATE SET config=excluded.config,updated_at=excluded.updated_at''',
        (college_id,plan.model_dump_json(),now.isoformat()))


def reserve(token, context, now):
    if not context.get('college_id'):
        return None
    with closing(classrooms.connect()) as db:
        db.execute('BEGIN IMMEDIATE')
        plan = get(db,context['college_id'])
        if plan is None:
            return None
        if context['template_id'] not in plan.templates:
            raise HTTPException(403,'This lab template is not included in your college plan.')
        local = now.astimezone(ZoneInfo(plan.timezone))
        oh,om = map(int,plan.opens.split(':')); ch,cm = map(int,plan.closes.split(':'))
        opening = local.replace(hour=oh,minute=om,second=0,microsecond=0)
        window_end = local.replace(hour=ch,minute=cm,second=0,microsecond=0)
        if local.weekday() not in plan.weekdays or not opening <= local < window_end:
            raise HTTPException(403,f'College access is closed. Approved hours: {plan.opens}–{plan.closes} ({plan.timezone}).')
        _,month_end = bounds(now,plan)
        deadline = min(window_end.astimezone(timezone.utc),month_end,
                       now+timedelta(minutes=context['session_minutes']+5))
        if (deadline-now).total_seconds() <= 300:
            raise HTTPException(403,'Too little time remains before closing to start a lab.')
        current = usage(db,context['college_id'],plan,now)
        # Include sessions predating the plan/ledger, conservatively.
        untracked = db.execute("""SELECT COUNT(*) FROM sessions s WHERE college_id=?
            AND status IN ('active','starting') AND expires_at>?
            AND NOT EXISTS(SELECT 1 FROM college_lab_usage u WHERE u.token=s.token)""",
            (context['college_id'],now.isoformat())).fetchone()[0]
        if current['active_labs']+untracked >= plan.seats:
            raise HTTPException(429,'All approved seats for your college are in use.')
        seconds = math.ceil((deadline-now).total_seconds())
        if current['reserved_seconds']+seconds > plan.monthly_hours*3600:
            raise HTTPException(429,'Your college has insufficient monthly lab-hours remaining for this session.')
        db.execute('INSERT INTO college_lab_usage(token,college_id,admitted_at,deadline) VALUES (?,?,?,?)',
                   (token,context['college_id'],now.isoformat(),deadline.isoformat()))
        db.commit()
        return deadline


def finish(db, token, now=None, failed=False):
    now = now or datetime.now(timezone.utc)
    db.execute('''UPDATE college_lab_usage SET ended_at=CASE WHEN ? THEN admitted_at ELSE ? END
        WHERE token=? AND ended_at IS NULL''',(failed,now.isoformat(),token))


def deadline(db, token):
    row = db.execute('SELECT deadline FROM college_lab_usage WHERE token=?',(token,)).fetchone()
    return datetime.fromisoformat(row[0]) if row else None


def reserve_storage(db, key, emails, limit_mb):
    college = db.execute('SELECT college_id FROM classrooms WHERE id=?',(key,)).fetchone()[0]
    for email in emails:
        db.execute('''INSERT INTO college_storage_reservations(classroom_id,email,limit_mb) VALUES (?,?,?)
            ON CONFLICT(classroom_id,email) DO UPDATE SET limit_mb=MAX(limit_mb,excluded.limit_mb)''',
            (key,email,limit_mb))
    plan = get(db,college)
    if plan:
        reserved = usage(db,college,plan,datetime.now(timezone.utc))['storage_reserved_mb']
        if reserved > plan.storage_mb:
            raise HTTPException(409,'This would exceed the college’s approved persistent-storage allowance. Update the college plan first.')
