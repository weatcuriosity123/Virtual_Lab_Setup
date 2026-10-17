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
