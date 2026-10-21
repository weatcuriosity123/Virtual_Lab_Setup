"""Real RSA/JWT verification with a local test key, plus HTTP ownership checks."""
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
from fastapi.testclient import TestClient

work=tempfile.TemporaryDirectory()
os.environ.update(SESSION_DB=work.name+'/db', SESSION_CONFIG_DIR=work.name+'/routes',
                  CLASS_ACCESS_CODE='legacy-test', AUTH_MODE='cloudflare',
                  ADMIN_EMAILS=' Admin@example.com, second@example.com ',
                  CF_ACCESS_TEAM_URL='https://test-team.cloudflareaccess.com', CF_ACCESS_AUD='test-audience')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
with patch('docker.from_env',return_value=MagicMock()):
    import main as lab
lab.docker_client.images.get.side_effect = lambda ref: MagicMock(attrs={"Config": {}}, id=ref)
import identity
import classrooms
identity.validate_config()
lab.init_db();lab.init_idle_db()
lab.reload_proxy=lambda:None
lab.delete_container=lambda name:None
lab.desktop_http_ready=lambda row:True
lab.installer_running=lambda name:False
private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
identity._client=SimpleNamespace(get_signing_key_from_jwt=lambda token:SimpleNamespace(key=private.public_key()))
with classrooms.connect() as db:
    db.execute("INSERT INTO colleges(id,name) VALUES('test','Test')")
    db.execute("""INSERT INTO lab_templates(id,name,image,memory_mb,cpu_millis,shm_mb,home_mb,pids)
        VALUES('linux','Linux','test-linux:1',768,750,256,300,256)""")
    digest,salt=classrooms.new_code(db,'class-secret')
    db.execute("""INSERT INTO classrooms(id,college_id,template_id,name,code_hash,code_salt,session_minutes,max_sessions)
        VALUES('test-class','test','linux','Test Class',?,?,60,4)""",(digest,salt))
    for email in ['alice@example.com','bob@example.com']:
        db.execute("INSERT INTO classroom_memberships(classroom_id,email) VALUES('test-class',?)",(email,))


def token(subject='alice',email='alice@example.com',**overrides):
    claims=dict(sub=subject,email=email,iss=identity.ISSUER,aud=[identity.AUDIENCE],
                iat=int(time.time()),exp=int(time.time())+600,type='app')
    claims.update(overrides)
    return jwt.encode(claims,private,algorithm='RS256',headers={'kid':'test-key'})


def headers(subject='alice',email='alice@example.com'):
    return {'Cf-Access-Jwt-Assertion':token(subject,email)}


client=TestClient(lab.app)
assert client.get('/health').status_code==200
assert client.get('/me').status_code==401
assert client.get('/me',headers={'Cf-Access-Authenticated-User-Email':'alice@example.com'}).status_code==401
for overrides in [{'exp':int(time.time())-1},{'aud':['wrong']},{'iss':'https://other.cloudflareaccess.com'},
                  {'type':'org'},{'email':None}]:
    assert client.get('/me',headers={'Cf-Access-Jwt-Assertion':token(**overrides)}).status_code==401
forged=jwt.encode(dict(sub='alice',email='alice@example.com',iss=identity.ISSUER,aud=identity.AUDIENCE,
                       iat=int(time.time()),exp=int(time.time())+600,type='app'),
                  rsa.generate_private_key(public_exponent=65537,key_size=2048),algorithm='RS256')
assert client.get('/me',headers={'Cf-Access-Jwt-Assertion':forged}).status_code==401
assert client.get('/me',headers=headers()).json()['email']=='alice@example.com'
assert client.post('/sessions',headers=headers('outsider','outsider@example.com'),json={'access_code':'class-secret'}).status_code==403
assert client.post('/sessions',headers=headers(),json={'access_code':'legacy-test'}).status_code==401
payload={'access_code':'class-secret','request_id':'a'*32}
response=client.post('/sessions',headers=headers(),json=payload)
assert response.status_code==200,response.text
session=response.json();sid=session['session_id'];password=session['desktop_password']
alice={**headers(),'X-Session-Password':password}
bob={**headers('bob','bob@example.com'),'X-Session-Password':password}
assert client.post('/sessions',headers=headers('bob','bob@example.com'),json=payload).status_code==403
assert client.post('/sessions',headers=headers(),json=payload).json()['session_id']==sid
for path in [f'/lab/{sid}',f'/lab/{sid}/activity',f'/lab/{sid}/ready']:
    assert client.get(path,headers=bob).status_code==403
assert client.post(f'/lab/{sid}/activate',headers=bob).status_code==403
assert client.post(f'/lab/{sid}/terminate',headers=bob).status_code==403
assert client.get('/desktop-authorize',headers={**bob,'X-Original-URI':f'/s/{sid}/'}).status_code==403
assert client.get('/desktop-authorize',headers={**alice,'X-Original-URI':f'/s/{sid}/?x=1'}).status_code==200
assert client.post(f'/lab/{sid}/activate',headers=alice).status_code==200
assert client.delete(f'/sessions/{sid}',params={'access_code':'class-secret'},headers=alice).status_code==403
with classrooms.connect() as db:
    db.execute("UPDATE classroom_memberships SET enabled=0 WHERE email='alice@example.com'")
assert client.get(f'/lab/{sid}',headers=alice).status_code==403
assert client.get('/desktop-authorize',headers={**alice,'X-Original-URI':f'/s/{sid}/'}).status_code==403
with classrooms.connect() as db:
    db.execute("UPDATE classroom_memberships SET enabled=1 WHERE email='alice@example.com'")
# Turning auth off must not expose a previously user-bound session.
identity.MODE='off'
assert client.get(f'/lab/{sid}',headers={'X-Session-Password':password}).status_code==403
identity.MODE='cloudflare'
assert client.post(f'/lab/{sid}/terminate',headers=alice).status_code==200
assert client.post(f'/lab/{sid}/feedback',headers=alice,json={'rating':5,'worked':'yes'}).status_code==200
print('PASS: signed identity, forged/expired/wrong-audience tokens, roster checks, owner-bound retries/API/desktop, revocation and downgrade protection')

# Admin privilege comes only from a verified JWT plus the server allowlist.
assert client.get('/admin/me').status_code == 401
assert client.get('/admin/me', headers=headers()).status_code == 403
for email in ['admin@example.com', 'second@example.com']:
    assert client.get('/admin/me', headers=headers('admin', email)).json()['role'] == 'admin'
    assert client.get('/me', headers=headers('admin', email)).json()['is_admin'] is True
assert client.get('/me', headers=headers()).json()['is_admin'] is False
assert client.get('/admin/me', headers={
    **headers(), 'Cf-Access-Authenticated-User-Email': 'admin@example.com'
}).status_code == 403
with patch.object(identity, 'MODE', 'off'):
    assert client.get('/admin/me', headers=headers('admin', 'admin@example.com')).status_code == 403
print('Admin authorization checks passed.')

admin_headers = {**headers('admin','admin@example.com'), 'X-Lab-Admin':'1'}
assert client.get('/admin/overview',headers=headers()).status_code == 403
assert client.get('/admin/overview').status_code == 401
assert client.post('/admin/colleges',headers=headers('admin','admin@example.com'),json={'id':'new','name':'New'}).status_code == 403
assert client.post('/admin/colleges',headers=admin_headers,json={'id':'new','name':'New'}).status_code == 200
assert client.post('/admin/colleges',headers=admin_headers,json={'id':'new','name':'New'}).status_code == 409
body=dict(id='new-class',name='New Class',college_id='new',template_id='linux',code='new-secret',session_minutes=30,max_sessions=2)
assert client.post('/admin/classrooms',headers=admin_headers,json=body).status_code == 200
assert client.post('/admin/classrooms',headers=admin_headers,json={**body,'id':'duplicate-code'}).status_code == 400
assert client.post('/admin/classrooms',headers=admin_headers,json={**body,'id':'missing','college_id':'missing','code':'other-secret'}).status_code == 409
assert client.post('/admin/classrooms/new-class/members',headers=admin_headers,json={'email':'Student@example.com'}).status_code == 200
assert client.post('/admin/classrooms/new-class/code',headers=headers(),json={'code':'stolen-secret'}).status_code == 403
assert client.post('/admin/classrooms/new-class/code',headers=admin_headers,json={'code':'rotated-secret'}).status_code == 200
with classrooms.connect() as db:
    assert classrooms.resolve_classroom(db,'new-secret') is None
    assert classrooms.resolve_classroom(db,'rotated-secret')['id'] == 'new-class'
assert client.post('/admin/classrooms/new-class/enabled',headers=admin_headers,json={'enabled':False}).status_code == 200
assert client.post('/admin/classrooms/new-class/members',headers=admin_headers,json={'email':'student@example.com','enabled':False}).status_code == 200
overview=client.get('/admin/overview',headers=admin_headers)
assert overview.status_code == 200
assert 'code_hash' not in overview.text and 'code_salt' not in overview.text and 'password' not in overview.text
assert next(r for r in overview.json()['classroom_memberships'] if r['email']=='student@example.com')['enabled'] == 0
assert client.post('/admin/sessions/missing/terminate',headers=admin_headers,json={}).status_code == 404
# Administrators can terminate an existing session without receiving desktop credentials.
with classrooms.connect() as db:
    db.execute("UPDATE sessions SET status='active' WHERE token=?",(session['session_id'],))
assert client.post('/admin/sessions/'+session['session_id']+'/terminate',headers=headers(),json={}).status_code == 403
assert client.post('/admin/sessions/'+session['session_id']+'/terminate',headers=admin_headers,json={}).status_code == 200
with classrooms.connect() as db:
    assert db.execute('SELECT status FROM sessions WHERE token=?',(session['session_id'],)).fetchone()[0]=='expired'
print('Admin management API checks passed.')

assert client.post('/admin/colleges',headers=admin_headers,json={'id':' COETrial ','name':'COE'}).status_code == 200
assert client.post('/admin/classrooms',headers=admin_headers,json={**body,'id':'PCCOER-Entc-2026','code':'MixedCaseCode'}).status_code == 200
with classrooms.connect() as db:
    assert db.execute("SELECT name FROM colleges WHERE id='coetrial'").fetchone()[0] == 'COE'
    assert classrooms.resolve_classroom(db,'MixedCaseCode')['id'] == 'pccoer-entc-2026'
    assert classrooms.resolve_classroom(db,'mixedcasecode') is None
assert client.post('/admin/colleges',headers=admin_headers,json={'id':'bad id','name':'Test'}).status_code == 422
print('Mixed-case ID normalization and case-sensitive code checks passed.')

bulk='/admin/classrooms/new-class/members/bulk'
assert client.post(bulk,headers=headers(),json={'emails':'outsider@example.com'}).status_code==403
assert client.post(bulk,headers=admin_headers,json={'emails':'valid@example.com,invalid-email'}).status_code==400
with classrooms.connect() as db:
    assert db.execute("SELECT 1 FROM classroom_memberships WHERE email='valid@example.com'").fetchone() is None
result=client.post(bulk,headers=admin_headers,json={'emails':'Student@example.com; new@example.com\nNEW@example.com'}).json()
assert result==dict(status='saved',added=1,reenabled=1,unchanged=0,duplicates=1)
result=client.post(bulk,headers=admin_headers,json={'emails':'student@example.com,new@example.com'}).json()
assert result['added']==0 and result['unchanged']==2
assert client.post(bulk,headers=admin_headers,json={'emails':'   '}).status_code==400
assert client.post(bulk,headers=admin_headers,json={'emails':','.join('u%d@example.com'%i for i in range(501))}).status_code==400
assert client.post('/admin/classrooms/missing/members/bulk',headers=admin_headers,json={'emails':'new@example.com'}).status_code==404
print('Bulk enrollment validation, atomicity, deduplication and retry checks passed.')

activity=client.get('/admin/overview',headers=admin_headers).json()['activity']
assert activity and all(row['actor_email']=='admin@example.com' for row in activity)
assert any(row['action']=='classroom.code_rotated' for row in activity)
assert any(row['action']=='session.terminated' for row in activity)
assert any(row['action']=='membership.bulk_enrolled' for row in activity)
serialized=str(activity)
assert 'rotated-secret' not in serialized and 'MixedCaseCode' not in serialized and password not in serialized
before=len(activity)
assert client.post('/admin/colleges',headers=admin_headers,json={'id':'new','name':'Duplicate'}).status_code==409
assert len(client.get('/admin/overview',headers=admin_headers).json()['activity'])==before
# An event-write failure must roll back its associated catalog change.
with patch('admin.json.dumps',side_effect=RuntimeError('test audit failure')):
    try:
        client.post('/admin/colleges',headers=admin_headers,json={'id':'rollback','name':'Rollback'})
    except RuntimeError:
        pass
with classrooms.connect() as db:
    assert db.execute("SELECT 1 FROM colleges WHERE id='rollback'").fetchone() is None
print('Admin activity attribution, redaction and transactional rollback checks passed.')

# Two-college boundary: faculty manage only their assignment; students stay non-admin.
faculty={**headers('faculty','faculty@example.com'),'X-Lab-Admin':'1'}
assert client.get('/admin/overview',headers=faculty).status_code==403
assert client.post('/admin/colleges/new/admins',headers=admin_headers,json={'email':'Faculty@example.com'}).status_code==200
assert client.get('/admin/me',headers=faculty).json()['role']=='college_admin'
assert client.get('/me',headers=faculty).json()['is_admin'] is True
view=client.get('/admin/overview',headers=faculty).json()
assert [c['id'] for c in view['colleges']]==['new']
assert all(c['college_id']=='new' for c in view['classrooms'])
assert all(e['college_id']=='new' for e in view['activity'])
assert view['college_admins']==[] and not view['platform_admin']
assert all('image' not in t for t in view['lab_templates'])
assert all(m['classroom_id']!='test-class' for m in view['classroom_memberships'])
for path,payload in [
    ('colleges',{'id':'forbidden','name':'Forbidden'}),
    ('colleges/new/enabled',{'enabled':False}),
    ('colleges/test/admins',{'email':'faculty@example.com'}),
    ('colleges/new/admins',{'email':'colleague@example.com'}),
    ('classrooms',{**body,'id':'foreign-class','college_id':'test','code':'foreign-code'}),
    ('classrooms/test-class/code',{'code':'foreign-code'}),
    ('classrooms/test-class/enabled',{'enabled':False}),
    ('classrooms/test-class/members',{'email':'intruder@example.com'}),
    ('classrooms/test-class/members/bulk',{'emails':'intruder@example.com'}),
    ('sessions/'+session['session_id']+'/terminate',{})]:
    assert client.post('/admin/'+path,headers=faculty,json=payload).status_code==403,path
assert client.post('/admin/classrooms',headers=faculty,json={**body,'id':'faculty-class','code':'faculty-code'}).status_code==403
assert client.post('/admin/classrooms',headers=admin_headers,json={**body,'id':'faculty-class','code':'faculty-code'}).status_code==200
assert client.post('/admin/classrooms/faculty-class/members/bulk',headers=faculty,json={'emails':'learner@example.com'}).status_code==403
assert client.post('/admin/classrooms/faculty-class/members/bulk',headers=admin_headers,json={'emails':'learner@example.com'}).status_code==200
assert client.post('/admin/classrooms/faculty-class/code',headers=faculty,json={'code':'faculty-rotated'}).status_code==200
assert client.post('/admin/classrooms/faculty-class/enabled',headers=faculty,json={'enabled':False}).status_code==200
# Make two active labs and feedback records, then verify scope before/after termination.
with classrooms.connect() as db:
    db.execute("UPDATE sessions SET status='active' WHERE token=?", (session['session_id'],))
    db.execute("""INSERT INTO sessions(token,container_name,password,created_at,expires_at,status,college_id,classroom_id,classroom_name)
        VALUES ('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','scoped-test','private-secret','2026-01-01','2099-01-01','active','new','faculty-class','Faculty Class')""")
    db.execute("INSERT INTO feedback(session_token,rating,worked,comments,submitted_at) VALUES ('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',5,'yes','Scoped feedback','2026-01-01')")
view=client.get('/admin/overview',headers=faculty).json()
assert [r['token'] for r in view['sessions']]==['aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa']
assert [r['comments'] for r in view['feedback']]==['Scoped feedback']
assert client.post('/admin/sessions/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/terminate',headers=faculty,json={}).status_code==200
assert client.post('/admin/colleges/new/admins',headers=admin_headers,json={'email':'faculty@example.com','enabled':False}).status_code==200
assert client.get('/admin/overview',headers=faculty).status_code==403
assert client.post('/admin/classrooms/faculty-class/code',headers=faculty,json={'code':'revoked-code'}).status_code==403
# Migration retains legacy events with no scope; these are platform-only.
with classrooms.connect() as db:
    db.execute("INSERT INTO admin_events(occurred_at,actor_email,action,target,details) VALUES ('2026-01-01','admin@example.com','legacy.event','private-target','{}')")
assert client.post('/admin/colleges/new/admins',headers=admin_headers,json={'email':'faculty@example.com'}).status_code==200
assert all(r['action']!='legacy.event' for r in client.get('/admin/overview',headers=faculty).json()['activity'])
assert any(r['action']=='legacy.event' for r in client.get('/admin/overview',headers=admin_headers).json()['activity'])
print('College admin isolation, assignment, revocation, feedback and session scope checks passed.')

# Exercise persistent mounts through the actual session creation API.
with classrooms.connect() as db:
    db.execute("UPDATE sessions SET status='expired'")
storage_context = dict(college_id='test', classroom_id='test-class', template_id='linux',
    college_name='Test', classroom_name='Test Class', template_name='Linux',
    image='test-linux:1', memory_mb=1536, cpu_millis=4000, shm_mb=256, home_mb=512,
    pids=512, max_sessions=4, session_minutes=30)
lab.docker_client.containers.list.return_value=[]
lab.docker_client.volumes.get.side_effect=lab.NotFound('missing')
lab.docker_client.volumes.create.side_effect=lambda **kw: SimpleNamespace(attrs={'Labels':kw['labels']})
with classrooms.connect() as db:
    db.execute("INSERT INTO storage_entitlements(classroom_id,email,persistent) VALUES('test-class','alice@example.com',1)")
with patch.dict(os.environ, {'PERSISTENT_HOME_TEMPLATES':'linux'}), patch.object(lab, 'admission_context', return_value=storage_context):
    created=client.post('/sessions',headers=headers(),json={'access_code':'class-secret'})
    assert created.status_code==200,created.text
    mounts=lab.docker_client.containers.run.call_args.kwargs
    assert 'tmpfs' not in mounts and list(mounts['volumes'].values())==[{'bind':'/config','mode':'rw'}]
    assert mounts['nano_cpus']==4000000000
    lab.docker_client.containers.list.return_value=[object()]
    duplicate=client.post('/sessions',headers=headers(),json={'access_code':'class-secret'})
    assert duplicate.status_code==409,duplicate.text
print('PASS: session API selects persistent mount and rejects simultaneous saved-home use')

# Subscription scopes, bulk atomicity, expiry and retained saved homes.
import storage
from datetime import datetime, timezone, timedelta
with patch.dict(os.environ, {'PERSISTENT_HOME_TEMPLATES':'linux'}):
    path='/admin/classrooms/test-class/storage'
    assert client.post(path,headers=headers(),json={'emails':'alice@example.com','persistent':True}).status_code==403
    assert client.post(path,headers=faculty,json={'emails':'alice@example.com','persistent':True}).status_code==403
    assert client.post(path,headers=admin_headers,json={'emails':'alice@example.com','persistent':True,'expires_at':'2000-01-01T00:00:00Z'}).status_code==422
    assert client.post(path,headers=admin_headers,json={'emails':'alice@example.com','persistent':True,'expires_at':'2099-01-01T00:00:00'}).status_code==422
    assert client.post(path,headers=admin_headers,json={'emails':'bob@example.com missing@example.com','persistent':True}).status_code==400
    assert not storage.subscription_active('test-class','bob@example.com')
    expiry=(datetime.now(timezone.utc)+timedelta(days=30)).isoformat()
    result=client.post(path,headers=admin_headers,json={'emails':'ALICE@example.com,bob@example.com,alice@example.com','persistent':True,'expires_at':expiry})
    assert result.status_code==200 and result.json()['students']==2,result.text
    assert storage.subscription_active('test-class','alice@example.com')
    assert storage.subscription_active('test-class','bob@example.com')
    assert client.post(path,headers=admin_headers,json={'emails':'bob@example.com','persistent':False}).status_code==200
    assert not storage.subscription_active('test-class','bob@example.com')
    with classrooms.connect() as db:
        db.execute("UPDATE storage_entitlements SET expires_at='2000-01-01T00:00:00+00:00' WHERE email='alice@example.com'")
    assert not storage.subscription_active('test-class','alice@example.com')
    # Expired homes use bounded tmpfs, without accessing or deleting Docker volumes.
    lab.docker_client.volumes.reset_mock()
    opts=storage.home_options(lab.docker_client,storage_context,SimpleNamespace(subject='alice',email='alice@example.com'),'cloudflare')
    assert opts=={'tmpfs':{'/config':'rw,size=512m,mode=1777'}}
    lab.docker_client.volumes.get.assert_not_called()
    lab.docker_client.volumes.remove.assert_not_called()
    assert all(e['classroom_id']!='test-class' for e in client.get('/admin/overview',headers=faculty).json()['storage_entitlements'])
print('PASS: storage subscriptions, scope protection, atomic bulk changes, expiry and temporary fallback')

# Permanent deletion is scoped, confirmed, attachment-safe, and never forced.
from unittest.mock import MagicMock
from docker.errors import APIError
with classrooms.connect() as db:
    homes=storage.known_homes(db)
home=next(h for h in homes.values() if h['classroom_id']=='test-class' and h['email']=='alice@example.com')
volume=MagicMock()
volume.name=home['name']
volume.attrs={'Driver':'local','Options':None,'Labels':{
    'linux-lab.storage':'home-v1','linux-lab.home':home['name'],
    'linux-lab.college':home['college_id'],'linux-lab.classroom':home['classroom_id'],
    'linux-lab.template':home['template_id']}}
lab.docker_client.volumes.list.return_value=[volume]
lab.docker_client.volumes.get.side_effect=None
lab.docker_client.volumes.get.return_value=volume
lab.docker_client.containers.list.return_value=[]
body={'name':home['name'],'confirmation':'DELETE alice@example.com'}
assert client.get('/admin/saved-homes',headers=headers()).status_code==403
assert client.get('/admin/saved-homes',headers=faculty).json()['homes']==[]
assert client.post('/admin/saved-homes/delete',headers=faculty,json=body).status_code==403
assert client.post('/admin/saved-homes/delete',headers=admin_headers,json={**body,'confirmation':'yes'}).status_code==400
lab.docker_client.containers.list.return_value=[object()]
assert client.post('/admin/saved-homes/delete',headers=admin_headers,json=body).status_code==409
volume.remove.assert_not_called()
lab.docker_client.containers.list.return_value=[]
volume.attrs['Options']={'type':'none','device':'/host/path','o':'bind'}
assert client.post('/admin/saved-homes/delete',headers=admin_headers,json=body).status_code==409
volume.remove.assert_not_called()
volume.attrs['Options']=None
volume.attrs['Labels']['linux-lab.classroom']='wrong'
assert client.post('/admin/saved-homes/delete',headers=admin_headers,json=body).status_code==409
volume.remove.assert_not_called()
volume.attrs['Labels']['linux-lab.classroom']=home['classroom_id']
volume.remove.side_effect=APIError('busy')
assert client.post('/admin/saved-homes/delete',headers=admin_headers,json=body).status_code==409
volume.remove.reset_mock();volume.remove.side_effect=None
with classrooms.connect() as db:
    before=dict(db.execute("SELECT * FROM storage_entitlements WHERE classroom_id='test-class' AND email='alice@example.com'").fetchone())
assert client.post('/admin/saved-homes/delete',headers=admin_headers,json=body).status_code==200
volume.remove.assert_called_once_with(force=False)
with classrooms.connect() as db:
    assert before==dict(db.execute("SELECT * FROM storage_entitlements WHERE classroom_id='test-class' AND email='alice@example.com'").fetchone())
    assert db.execute("SELECT COUNT(*) FROM admin_events WHERE action='membership.home_deleted'").fetchone()[0]==1
print('PASS: permanent home deletion scope, confirmation, labels, attachment guard, failure handling and audit')

# Quota backend admission, owner-only usage and fail-closed provisioning.
with classrooms.connect() as db:
    db.execute("UPDATE sessions SET status='expired'")
    db.execute("UPDATE storage_entitlements SET persistent=1,expires_at=NULL,limit_mb=300 WHERE classroom_id='test-class' AND email='alice@example.com'")
quota_name=home['name']+'-quota'
with patch.dict(os.environ, {'PERSISTENT_HOME_TEMPLATES':'linux','PERSISTENT_STORAGE_BACKEND':'quota'}), patch.object(lab,'admission_context',return_value=storage_context):
    with patch.object(storage,'quota_rpc',return_value={'volume':quota_name,'state':'ready','used_bytes':4096,'limit_bytes':300*1048576}) as rpc:
        created=client.post('/sessions',headers=headers(),json={'access_code':'class-secret'})
        assert created.status_code==200,created.text
        rpc.assert_called_once_with('ensure',name=home['name'],scope={'college_id':'test','classroom_id':'test-class','template_id':'linux'},limit_mb=300)
        assert quota_name in lab.docker_client.containers.run.call_args.kwargs['volumes']
        info=created.json();sid=info['session_id'];pwd=info['desktop_password']
        response=client.get('/lab/'+sid+'/storage',headers={**headers(),'X-Session-Password':pwd})
        assert response.status_code==200 and response.json()['limit_bytes']==300*1048576
        assert client.get('/lab/'+sid+'/storage',headers={**headers('bob','bob@example.com'),'X-Session-Password':pwd}).status_code==403
    before=lab.docker_client.containers.run.call_count
    from fastapi import HTTPException
    with patch.object(storage,'quota_rpc',side_effect=HTTPException(503,'Storage offline')):
        assert client.post('/sessions',headers=headers(),json={'access_code':'class-secret'}).status_code==503
    assert lab.docker_client.containers.run.call_count==before
    assert client.post('/admin/classrooms/test-class/storage',headers=admin_headers,json={'emails':'alice@example.com','persistent':True,'limit_mb':63}).status_code==422
print('PASS: quota mounts, allowance forwarding, owner usage authorization and fail-closed service outage')

# Dashboard routes quota homes to the broker, retaining typed confirmation and audit.
with patch.dict(os.environ, {'PERSISTENT_STORAGE_BACKEND':'quota'}):
    def broker(op,**fields):
        if op=='list': return {'homes':[{'name':home['name'],'state':'ready','used_bytes':4096,'limit_bytes':300*1048576}]}
        if op=='info': return {'state':'ready'}
        if op=='delete': return {'deleted':True,'original_backup_retained':True}
        raise AssertionError(op)
    with patch.object(storage,'quota_rpc',side_effect=broker) as rpc:
        lab.docker_client.containers.list.return_value=[]
        view=client.get('/admin/saved-homes',headers=admin_headers).json()['homes']
        assert len(view)==1 and view[0]['backend']=='quota'
        assert client.get('/admin/saved-homes',headers=faculty).json()['homes']==[]
        before=volume.remove.call_count
        response=client.post('/admin/saved-homes/delete',headers=admin_headers,json=body)
        assert response.status_code==200 and response.json()['original_backup_retained']
        assert volume.remove.call_count==before
        assert any(c.args==('delete',) for c in rpc.call_args_list)
print('PASS: quota home dashboard isolation and broker-based deletion')

# Host-wide health is platform-only, with safe failure messages and disk warnings.
import admin as admin_module
with patch.object(lab.docker_client, 'ping') as ping:
    assert client.get('/admin/system-health').status_code == 401
    assert client.get('/admin/system-health', headers=headers()).status_code == 403
    assert client.get('/admin/system-health', headers=faculty).status_code == 403
    ping.assert_not_called()
with patch.object(lab.docker_client, 'ping', side_effect=RuntimeError('secret-internal-detail')), \
     patch.object(admin_module.disk_guard, 'snapshot', return_value=[{'name':'Database filesystem space','status':'CRITICAL','detail':'Low space'}]):
    response=client.get('/admin/system-health', headers=admin_headers)
    assert response.status_code == 200
    assert 'secret-internal-detail' not in response.text
    checks={r['name']:r for r in response.json()['checks']}
    assert checks['Docker']['status']=='UNAVAILABLE'
    assert checks['Database filesystem space']['status']=='CRITICAL'
print('System health authorization, failure redaction and low-disk checks passed.')


# Approval workflow: requests cannot grant access; only portal admins apply them.
def request(kind, target, payload, who=faculty):
    return client.post('/admin/requests', headers=who,
                       json={'kind':kind,'target':target,'payload':payload,'reason':'Course practical'})
def review(rid, approve=True, **kwargs):
    return client.post(f'/admin/requests/{rid}/review', headers=admin_headers,
                       json={'approve':approve,'note':'Reviewed for pilot','code':kwargs.get('code')})
with patch.dict(os.environ, {'PERSISTENT_HOME_TEMPLATES':'linux'}):
    storage_payload={'emails':'learner@example.com','persistent':True,'limit_mb':2048,'expires_at':None}
    assert client.post('/admin/classrooms/faculty-class/storage',headers=faculty,json=storage_payload).status_code==403
    assert client.post('/admin/classrooms/faculty-class/members',headers=faculty,json={'email':'new@example.com'}).status_code==403
    assert client.post('/admin/classrooms/faculty-class/enabled',headers=faculty,json={'enabled':True}).status_code==403
    assert request('storage','test-class',storage_payload).status_code==403
    assert request('storage','faculty-class',storage_payload,headers()).status_code==403
    assert request('storage','faculty-class',{**storage_payload,'limit_mb':99999}).status_code==400
    assert request('storage','faculty-class',{**storage_payload,'emails':'missing@example.com'}).status_code==400
    response=request('storage','faculty-class',storage_payload)
    assert response.status_code==200,response.text
    rid=response.json()['id']
    assert request('storage','faculty-class',storage_payload).json()['id']==rid
    with classrooms.connect() as db:
        assert db.execute("SELECT * FROM storage_entitlements WHERE classroom_id='faculty-class'").fetchone() is None
    assert client.post(f'/admin/requests/{rid}/review',headers=faculty,json={'approve':True}).status_code==403
    approved_response=review(rid)
    assert approved_response.status_code==200,approved_response.text
    assert review(rid).status_code==409
    with classrooms.connect() as db:
        entry=db.execute("SELECT * FROM storage_entitlements WHERE classroom_id='faculty-class'").fetchone()
        assert entry['persistent']==1 and entry['expires_at'] is None and entry['limit_mb']==2048
    # Direct platform editing of a previously indefinite expiry preserves explicit quota.
    future='2099-01-01T00:00:00Z'
    assert client.post('/admin/classrooms/faculty-class/storage',headers=admin_headers,json={**storage_payload,'expires_at':future}).status_code==200
    view=client.get('/admin/overview',headers=faculty).json()
    assert any(e['expires_at'] and e['limit_mb']==2048 for e in view['storage_entitlements'])
    assert all('baseline' not in r for r in view['requests'])
    # Reject without changing access.
    rid=request('storage','faculty-class',{**storage_payload,'limit_mb':4096}).json()['id']
    assert review(rid,False).status_code==200
    with classrooms.connect() as db:
        assert db.execute("SELECT limit_mb FROM storage_entitlements WHERE classroom_id='faculty-class'").fetchone()[0]==2048
    # A newer platform decision cannot be overwritten by an older pending request.
    rid=request('storage','faculty-class',storage_payload).json()['id']
    assert client.post('/admin/classrooms/faculty-class/storage',headers=admin_headers,json={**storage_payload,'limit_mb':1024}).status_code==200
    assert review(rid).status_code==409
    assert review(rid,False).status_code==200
    # Approval audit failure rolls back both entitlement and request status.
    rid=request('storage','faculty-class',storage_payload).json()['id']
    original_dumps=__import__('json').dumps
    def fail_audit(value, *args, **kwargs):
        if isinstance(value,dict) and value.get('note')=='Reviewed for pilot':
            raise RuntimeError('audit unavailable')
        return original_dumps(value,*args,**kwargs)
    with patch('admin.json.dumps',side_effect=fail_audit):
        try:
            review(rid)
            raise AssertionError('Audit failure did not propagate')
        except RuntimeError:
            pass
    with classrooms.connect() as db:
        assert db.execute('SELECT status FROM admin_requests WHERE id=?',(rid,)).fetchone()[0]=='pending'
        assert db.execute("SELECT limit_mb FROM storage_entitlements WHERE classroom_id='faculty-class'").fetchone()[0]==1024
    assert review(rid).status_code==200
# Enrollment requests, normalization, and scope visibility.
rid=request('enrollment','faculty-class',{'emails':'NEW@example.com,new@example.com'}).json()['id']
with classrooms.connect() as db:
    assert db.execute("SELECT 1 FROM classroom_memberships WHERE classroom_id='faculty-class' AND email='new@example.com'").fetchone() is None
assert review(rid).status_code==200
with classrooms.connect() as db:
    assert db.execute("SELECT count(*) FROM classroom_memberships WHERE classroom_id='faculty-class' AND email='new@example.com'").fetchone()[0]==1
rid=request('classroom_enable','faculty-class',{'enabled':True}).json()['id']
assert review(rid).status_code==200
proposal={'id':'approved-class','name':'Approved Class','template_id':'linux','session_minutes':30,'max_sessions':1}
rid=request('classroom_create','new',proposal).json()['id']
assert review(rid).status_code==400
assert review(rid,code='approved-secret').status_code==200
with classrooms.connect() as db:
    approved=db.execute("SELECT * FROM classrooms WHERE id='approved-class'").fetchone()
    assert approved['max_sessions']==1 and classrooms.matches('approved-secret',approved)
view=client.get('/admin/overview',headers=faculty).json()
assert all(r['college_id']=='new' for r in view['requests'])
assert 'approved-secret' not in str(view)
# Requests from another college stay invisible.
rid=request('enrollment','test-class',{'emails':'other@example.com'},admin_headers).json()['id']
assert rid not in [r['id'] for r in client.get('/admin/overview',headers=faculty).json()['requests']]
# Double approval is serialized; exactly one succeeds.
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor(max_workers=2) as pool:
    results=list(pool.map(lambda _:review(rid).status_code,range(2)))
assert sorted(results)==[200,409],results
print('PASS: platform-only storage and cost controls, scoped requests, expiry editing, atomic approval/rejection, stale protection and concurrent reviews')


# College plans: role checks, scoped visibility, approval, and actual admission wiring.
import plans
plan_body=dict(seats=1,monthly_hours=20,storage_mb=8192,templates=['linux'],timezone='UTC',weekdays=list(range(7)),opens='00:00',closes='23:59')
assert client.post('/admin/colleges/new/plan',headers=faculty,json=plan_body).status_code==403
assert client.post('/admin/colleges/new/plan',headers=admin_headers,json={**plan_body,'closes':'00:00'}).status_code==422
assert client.post('/admin/colleges/new/plan',headers=admin_headers,json=plan_body).status_code==200
assert request('college_plan','test',plan_body).status_code==403
rid=request('college_plan','new',{**plan_body,'monthly_hours':30}).json()['id']
assert review(rid).status_code==200
view=client.get('/admin/overview',headers=faculty).json()
assert len(view['plans'])==1 and view['plans'][0]['config']['monthly_hours']==30
with classrooms.connect() as db:
    db.execute("UPDATE sessions SET status='expired'")
# Failed launch returns its reservation; retrying a successful request does not charge twice.
lab.docker_client.containers.run.side_effect=RuntimeError('test launch failure')
assert client.post('/sessions',headers=headers('learner','learner@example.com'),json={'access_code':'faculty-rotated','request_id':'e'*32}).status_code==500
with classrooms.connect() as db:
    assert plans.usage(db,'new',plans.get(db,'new'),datetime.now(timezone.utc))['reserved_seconds']==0
lab.docker_client.containers.run.side_effect=None
started=client.post('/sessions',headers=headers('learner','learner@example.com'),json={'access_code':'faculty-rotated','request_id':'f'*32})
assert started.status_code==200,started.text
retry=client.post('/sessions',headers=headers('learner','learner@example.com'),json={'access_code':'faculty-rotated','request_id':'f'*32})
assert retry.status_code==200 and retry.json()['session_id']==started.json()['session_id']
assert client.post('/sessions',headers=headers('other','new@example.com'),json={'access_code':'faculty-rotated'}).status_code==429
assert client.post('/admin/colleges/new/plan',headers=admin_headers,json=plan_body).status_code==409
sid=started.json()['session_id']
owner={**headers('learner','learner@example.com'),'X-Session-Password':started.json()['desktop_password']}
# Simulate a near closing boundary while readiness completes; activation must preserve it.
cap=datetime.now(timezone.utc)+timedelta(minutes=2)
with classrooms.connect() as db:
    db.execute('UPDATE college_lab_usage SET deadline=? WHERE token=?',(cap.isoformat(),sid))
assert client.post('/lab/'+sid+'/activate',headers=owner).status_code==200
with classrooms.connect() as db:
    assert datetime.fromisoformat(db.execute('SELECT expires_at FROM sessions WHERE token=?',(sid,)).fetchone()[0])==cap
assert client.post('/lab/'+sid+'/terminate',headers=owner).status_code==200
with classrooms.connect() as db:
    assert db.execute('SELECT ended_at FROM college_lab_usage WHERE token=?',(sid,)).fetchone()[0]
# Cap applies to direct portal edits as well as approvals, with all-or-nothing rollback.
with patch.dict(os.environ,{'PERSISTENT_HOME_TEMPLATES':'linux'}):
    assert client.post('/admin/classrooms/faculty-class/storage',headers=admin_headers,json={'emails':'learner@example.com','persistent':True,'limit_mb':16384}).status_code==409
    rid=request('storage','faculty-class',{'emails':'learner@example.com','persistent':True,'limit_mb':16384}).json()['id']
    assert review(rid).status_code==409
    with classrooms.connect() as db:
        assert db.execute('SELECT status FROM admin_requests WHERE id=?',(rid,)).fetchone()[0]=='pending'
        assert plans.usage(db,'new',plans.get(db,'new'),datetime.now(timezone.utc))['storage_reserved_mb']<=8192
print('PASS: college-plan role and approval boundaries, live admission limits, retry accounting, failed-launch refund, closing-time activation and storage-cap rollback')
