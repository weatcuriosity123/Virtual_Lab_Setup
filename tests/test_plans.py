"""Deterministic college budget, calendar and serialized admission tests."""
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from fastapi import HTTPException
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import classrooms
import plans

work=tempfile.TemporaryDirectory()
os.environ['SESSION_DB']=work.name+'/db'
with classrooms.connect() as db:
    classrooms.init_catalog(db)
    db.execute('CREATE TABLE sessions(token TEXT PRIMARY KEY,college_id TEXT,status TEXT,expires_at TEXT)')
    db.execute("INSERT INTO colleges(id,name) VALUES ('a','A'),('b','B')")
    db.execute("INSERT INTO lab_templates VALUES ('lite','Lite','image',768,1000,128,300,256,1)")
    db.execute("INSERT INTO classrooms VALUES ('a1','a','lite','A1','h','s',60,3,NULL,1),('a2','a','lite','A2','h','s',60,3,NULL,1),('b1','b','lite','B1','h','s',60,3,NULL,1)")
    db.execute("INSERT INTO classroom_memberships VALUES ('a1','x@example.com',1),('a1','y@example.com',1)")
now=datetime(2026,10,21,5,0,tzinfo=timezone.utc)  # Wednesday 10:30 IST
config=dict(seats=1,monthly_hours=3,storage_mb=2048,templates=['lite'],timezone='Asia/Kolkata',weekdays=[0,1,2,3,4],opens='10:00',closes='17:00')
plan=plans.CollegePlan(**config)
context=dict(college_id='a',classroom_id='a1',template_id='lite',session_minutes=60)
def failure(code, fn):
    try: fn()
    except HTTPException as exc: assert exc.status_code==code,(exc.status_code,exc.detail)
    else: raise AssertionError('Expected denial')
def save(value):
    with classrooms.connect() as db: plans.save(db,'a',value,now)
def finish(token, minutes=10, failed=False):
    with classrooms.connect() as db: plans.finish(db,token,now+timedelta(minutes=minutes),failed)
save(plan)
assert plans.reserve('unconfigured',{**context,'college_id':'b'},now) is None
failure(403,lambda:plans.reserve('wrong', {**context,'template_id':'other'},now))
failure(403,lambda:plans.reserve('early',context,now.replace(hour=3)))
failure(403,lambda:plans.reserve('weekend',context,now+timedelta(days=3)))
assert plans.reserve('one',context,now)==now+timedelta(minutes=65)
failure(429,lambda:plans.reserve('two',{**context,'classroom_id':'a2'},now))
failure(409,lambda:save(plan))
with classrooms.connect() as db:
    u=plans.usage(db,'a',plan,now+timedelta(minutes=2))
    assert u['used_seconds']==120 and u['reserved_seconds']==3900
finish('one')
with classrooms.connect() as db:
    u=plans.usage(db,'a',plan,now+timedelta(minutes=20))
    assert u['used_seconds']==600 and u['reserved_seconds']==600 and u['active_labs']==0
# Only one of two independent connections can reserve the final seat.
def start(token):
    try: plans.reserve(token,context,now+timedelta(minutes=20)); return 200
    except HTTPException as exc: return exc.status_code
with ThreadPoolExecutor(max_workers=2) as pool:
    assert sorted(pool.map(start,['race-a','race-b']))==[200,429]
finish('race-a',failed=True);finish('race-b',failed=True)
# Session closing deadline is absolute, not a new full timer on activation.
late=datetime(2026,10,21,11,0,tzinfo=timezone.utc)
assert plans.reserve('late',context,late)==datetime(2026,10,21,11,30,tzinfo=timezone.utc)
with classrooms.connect() as db: plans.finish(db,'late',late,failed=True)
failure(403,lambda:plans.reserve('too-late',context,late+timedelta(minutes=26)))
# Monthly admission includes existing usage plus the entire reserved session.
save(plans.CollegePlan(**{**config,'monthly_hours':1}))
failure(429,lambda:plans.reserve('over-budget',context,now+timedelta(minutes=30)))
short={**context,'session_minutes':30}
assert plans.reserve('short',short,now+timedelta(minutes=30))
finish('short',failed=True)
# New calendar month ignores previous month's settled charges.
next_month=datetime(2026,11,2,5,0,tzinfo=timezone.utc)
assert plans.reserve('november',short,next_month)
with classrooms.connect() as db:
    assert plans.usage(db,'a',plan,next_month)['reserved_seconds']==2100
    plans.finish(db,'november',next_month,failed=True)
# Storage bulk failure rolls back all reservations; quotas cannot be recycled by disabling.
with classrooms.connect() as db: plans.reserve_storage(db,'a1',['x@example.com'],1536)
def over_storage():
    with classrooms.connect() as db: plans.reserve_storage(db,'a1',['y@example.com'],1024)
failure(409,over_storage)
with classrooms.connect() as db:
    assert db.execute("SELECT 1 FROM college_storage_reservations WHERE email='y@example.com'").fetchone() is None
    plans.reserve_storage(db,'a1',['x@example.com'],512)
    assert plans.usage(db,'a',plan,now)['storage_reserved_mb']==1536
failure(409,lambda:save(plans.CollegePlan(**{**config,'storage_mb':1024})))
failure(409,lambda:save(plans.CollegePlan(**{**config,'timezone':'UTC'})))
# Migration is repeatable and preserves the conservative high-water reservation.
with classrooms.connect() as db:
    classrooms.init_catalog(db)
    assert plans.usage(db,'a',plan,now)['storage_reserved_mb']==1536
print('PASS: college seats across classrooms, template/time guards, monthly accounting, early-end refunds, failed-start refunds, month rollover, concurrent admission and retained storage reservations')
