"""Lifecycle checks against temporary SQLite; Docker and HTTP probes are mocked."""
import asyncio
import os
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

work = tempfile.TemporaryDirectory()
os.environ.update(CLASS_ACCESS_CODE='test-code', SESSION_DB=work.name+'/sessions.db',
                  SESSION_CONFIG_DIR=work.name+'/routes', SESSION_MINUTES='60', MAX_SESSIONS='4')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
with patch('docker.from_env', return_value=MagicMock()):
    import main as lab
lab.docker_client.images.get.side_effect = lambda ref: MagicMock(attrs={"Config": {}}, id=ref)

lab.init_db()
lab.init_db()  # migration must be repeatable
lab.init_idle_db()
lab.reload_proxy = lambda: None
lab.delete_container = MagicMock()
lab.installer_running = lambda name: False

async def expect_error(code, call):
    try:
        await call
    except lab.HTTPException as error:
        assert error.status_code == code, error
    else:
        raise AssertionError(f'Expected HTTP {code}')

async def run():
    await expect_error(401, lab.create_session(lab.CreateSession(access_code='wrong')))
    request = lab.CreateSession(access_code='test-code', request_id='a'*32)
    with patch.object(lab.disk_guard, 'require_space', side_effect=lab.HTTPException(503, 'Low disk')), patch.object(lab.storage, 'home_options') as homes:
        await expect_error(503, lab.create_session(request))
        homes.assert_not_called()
        lab.docker_client.containers.run.assert_not_called()
    session = await lab.create_session(request)
    assert lab.docker_client.containers.run.call_args.kwargs['log_config']['Config']=={'max-size':'10m','max-file':'3'}
    token, password = session['session_id'], session['desktop_password']
    assert session['status'] == 'starting'
    assert lab.session_capacity()['active_sessions'] == 1
    assert (await lab.create_session(request))['session_id'] == token
    assert lab.docker_client.containers.run.call_count == 1
    assert (await lab.lab_status(token, password))['remaining_seconds'] == 0
    assert not (await lab.record_lab_activity(token, password))['tracking']
    await expect_error(403, lab.desktop_readiness(token, 'wrong'))
    lab.desktop_http_ready = lambda row: False
    await expect_error(503, lab.activate_desktop(token, password))
    lab.desktop_http_ready = lambda row: True
    active = await lab.activate_desktop(token, password)
    assert active['status'] == 'active'
    assert 3590 < (datetime.fromisoformat(active['expires_at']) - datetime.now(timezone.utc)).total_seconds() <= 3600
    assert (await lab.activate_desktop(token, password))['expires_at'] == active['expires_at']
    for _ in range(3):
        await lab.create_session(lab.CreateSession(access_code='test-code'))
    await expect_error(429, lab.create_session(lab.CreateSession(access_code='test-code')))
    with lab.connect_db() as db:
        db.execute('UPDATE lab_activity SET last_activity=last_activity-181 WHERE token=?', (token,))
    assert (await lab.read_lab_activity(token, password))['warning']
    with lab.connect_db() as db:
        db.execute('UPDATE lab_activity SET last_activity=last_activity-60 WHERE token=?', (token,))
    result = await lab.record_lab_activity(token, password)
    assert result['status'] == 'expired' and result['end_reason'] == 'inactivity'
    assert (await lab.submit_lab_feedback(token, lab.LabFeedback(rating=5, worked='yes'), password))['status'] == 'saved'
    await expect_error(409, lab.activate_desktop(token, password))
    await expect_error(409, lab.create_session(request))
    fresh = await lab.create_session(lab.CreateSession(access_code='test-code'))
    assert (await lab.terminate_lab(fresh['session_id'], fresh['desktop_password']))['status'] == 'terminated'
    fresh = await lab.create_session(lab.CreateSession(access_code='test-code'))
    with lab.connect_db() as db:
        db.execute('UPDATE sessions SET expires_at=? WHERE token=?',
                   ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(), fresh['session_id']))
    lab.cleanup_expired()
    assert (await lab.lab_status(fresh['session_id'], fresh['desktop_password']))['status'] == 'expired'
    print('PASS: lifecycle, retry, capacity, auth, activation, resume expiry, idle, feedback and cleanup')

if __name__ == '__main__':
    asyncio.run(run())
