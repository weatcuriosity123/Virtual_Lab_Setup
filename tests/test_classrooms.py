"""Admission isolation and migration tests; no real Docker or college credentials."""
import asyncio
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from unittest.mock import MagicMock, patch

work = tempfile.TemporaryDirectory()
os.environ.update(SESSION_DB=work.name+'/db', SESSION_CONFIG_DIR=work.name+'/routes',
                  CLASS_ACCESS_CODE='legacy-test', ALLOW_LEGACY_CLASS_CODE='true')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
# Start with the older schema and a real pre-migration row.
with sqlite3.connect(os.environ['SESSION_DB']) as db:
    db.execute('''CREATE TABLE sessions(token TEXT PRIMARY KEY, container_name TEXT NOT NULL,
      password TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, status TEXT NOT NULL)''')
    now = datetime.now(timezone.utc)
    db.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?)',
               ('f'*32,'old-container','old-password',now.isoformat(),(now+timedelta(hours=1)).isoformat(),'active'))
with patch('docker.from_env', return_value=MagicMock()):
    import main as lab
lab.docker_client.images.get.side_effect = lambda ref: MagicMock(attrs={"Config": {}}, id=ref)
import classrooms as catalog
lab.init_db(); lab.init_db(); lab.init_idle_db()
lab.reload_proxy = lambda: None
lab.delete_container = lambda name: None
lab.desktop_http_ready = lambda row: True


def cli(args, code=None):
    out = io.StringIO()
    with patch.object(sys, 'argv', ['classrooms.py']+args), patch.object(catalog,'prompt_code',return_value=code), redirect_stdout(out):
        catalog.main()
    return out.getvalue()


async def error(status, operation):
    try:
        await operation
    except lab.HTTPException as exc:
        assert exc.status_code == status, exc
    else:
        raise AssertionError(f'Expected HTTP {status}')


async def run():
    assert (await lab.lab_status('f'*32,'old-password'))['status']=='active'
    await lab.terminate_lab('f'*32,'old-password')
    cli(['college-add','test-college','--name','Test College'])
    cli(['template-add','linux','--name','Linux','--image','test-linux:1'])
    cli(['template-add','robotics','--name','Robotics test','--image','test-robotics:1',
         '--memory-mb','2048','--cpu-millis','1500','--shm-mb','512','--home-mb','600','--pids','512'])
    for name,template,code,minutes in [('linux-class','linux','linux-secret',30),('robot-class','robotics','robot-secret',45)]:
        cli(['classroom-add',name,'--college','test-college','--template',template,'--name',name,
             '--minutes',str(minutes),'--slots','1'],code)
    public_list = cli(['list'])
    assert 'secret' not in public_list and 'code_hash' not in public_list and 'code_salt' not in public_list
    with catalog.connect() as db:
        try: catalog.new_code(db,'linux-secret')
        except ValueError: pass
        else: raise AssertionError('Duplicate code accepted')
    request=lambda code,id=None: lab.CreateSession(access_code=code,request_id=id)
    linux=await lab.create_session(request('linux-secret','a'*32))
    assert linux['college_name']=='Test College' and linux['session_minutes']==30
    assert (await lab.create_session(request('linux-secret','a'*32)))['session_id']==linux['session_id']
    await error(409,lab.create_session(request('robot-secret','a'*32)))
    await error(404,lab.end_session(linux['session_id'],'robot-secret'))
    await error(404,lab.end_session(linux['session_id'],'legacy-test'))
    await error(429,lab.create_session(request('linux-secret')))
    robot=await lab.create_session(request('robot-secret'))
    options=lab.docker_client.containers.run.call_args.kwargs
    assert options['image']=='test-robotics:1' and options['mem_limit']=='2048m'
    assert options['nano_cpus']==1_500_000_000 and options['shm_size']=='512m'
    assert options['pids_limit']==512 and '600m' in options['tmpfs']['/config']
    assert options['labels']['linux-lab.classroom']=='robot-class'
    # Editing classroom settings cannot change a previously admitted session's duration.
    with catalog.connect() as db:
        db.execute("UPDATE classrooms SET session_minutes=99 WHERE id='robot-class'")
    active=await lab.activate_desktop(robot['session_id'],robot['desktop_password'])
    duration=(datetime.fromisoformat(active['expires_at'])-datetime.now(timezone.utc)).total_seconds()
    assert 2690 < duration <= 2700
    assert (await lab.activate_desktop(robot['session_id'],robot['desktop_password']))['expires_at']==active['expires_at']
    lab.MAX_SESSIONS=2
    await error(429,lab.create_session(request('legacy-test')))
    lab.MAX_SESSIONS=4
    cli(['code-rotate','linux-class'],'linux-rotated')
    await error(401,lab.create_session(request('linux-secret')))
    # Existing credentials survive code rotation, disabling and expiry.
    cli(['set-enabled','classroom','linux-class','no'])
    assert (await lab.lab_status(linux['session_id'],linux['desktop_password']))['status']=='starting'
    await error(401,lab.create_session(request('linux-rotated')))
    cli(['set-enabled','classroom','linux-class','yes'])
    cli(['set-enabled','college','test-college','no'])
    await error(401,lab.create_session(request('robot-secret')))
    cli(['set-enabled','college','test-college','yes'])
    cli(['set-enabled','template','robotics','no'])
    await error(401,lab.create_session(request('robot-secret')))
    with catalog.connect() as db:
        db.execute("UPDATE classrooms SET expires_at=? WHERE id='linux-class'",
                   ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),))
    await error(401,lab.create_session(request('linux-rotated')))
    await error(401,lab.create_session(request('wrong-code')))
    legacy=await lab.create_session(request('legacy-test'))
    assert lab.docker_client.containers.run.call_args.kwargs['image']==lab.STUDENT_IMAGE
    lab.ALLOW_LEGACY_CLASS_CODE=False
    await error(401,lab.create_session(request('legacy-test')))
    assert (await lab.lab_status(legacy['session_id'],legacy['desktop_password']))['status']=='starting'
    print('PASS: old-schema migration, CLI, hashed codes, scoped retries/deletion, quotas, template resources, duration snapshot, rotation/disable/expiry, legacy compatibility')


asyncio.run(run())
