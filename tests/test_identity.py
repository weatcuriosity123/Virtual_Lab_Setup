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
