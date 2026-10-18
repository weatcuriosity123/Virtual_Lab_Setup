"""Startup recovery with temporary SQLite and mocked Docker ownership/state."""
import os
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import unittest

work = tempfile.TemporaryDirectory()
os.environ.update(CLASS_ACCESS_CODE='test', SESSION_DB=work.name+'/sessions.db', SESSION_CONFIG_DIR=work.name+'/routes')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
with patch('docker.from_env', return_value=MagicMock()):
    import main as lab
lab.init_db()


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        with lab.connect_db() as db:
            db.execute('DELETE FROM sessions')
        for p in lab.CONFIG_DIR.glob('*.conf'):
            p.unlink()
        lab.docker_client.reset_mock()
        lab.docker_client.containers.list.side_effect = None
        lab.reload_proxy = MagicMock()

    def row(self, token, status='active', expired=False):
        expiry = (datetime.now(timezone.utc)+timedelta(minutes=-1 if expired else 20)).isoformat()
        with lab.connect_db() as db:
            db.execute('INSERT INTO sessions(token,container_name,password,created_at,expires_at,status,home_volume) VALUES(?,?,?,?,?,?,?)',
                       (token, 'linux-lab-session-'+token, 'secret', datetime.now(timezone.utc).isoformat(), expiry, status, 'saved-home'))
        return expiry

    def container(self, token, status='running'):
        c = MagicMock()
        c.name = 'linux-lab-session-'+token
        c.labels = {'linux-lab.managed':'true', 'linux-lab.session':token}
        c.status = status
        return c

    def status(self, token):
        with lab.connect_db() as db:
            return db.execute('SELECT status,expires_at FROM sessions WHERE token=?',(token,)).fetchone()

    def test_preserves_running_sessions_and_deadlines(self):
        a,b = 'a'*32,'b'*32
        expiry = self.row(a)
        self.row(b, 'starting')
        containers = [self.container(a), self.container(b)]
        lab.docker_client.containers.list.return_value = containers
        lab.reconcile_sessions()
        self.assertEqual(tuple(self.status(a)), ('active',expiry))
        self.assertEqual(self.status(b)[0], 'starting')
        for c in containers:
            c.remove.assert_not_called()
        self.assertTrue((lab.CONFIG_DIR/(a+'.conf')).exists())

    def test_missing_stopped_expired_orphan_and_stale_route(self):
        a,b,c,d = (x*32 for x in 'abcd')
        self.row(a)
        self.row(b)
        self.row(c, expired=True)
        containers = [self.container(b, 'exited'), self.container(c), self.container(d)]
        lab.docker_client.containers.list.return_value = containers
        for token in (a,b,c,d):
            lab.write_route(token, 'unused')
        lab.reconcile_sessions()
        for token in (a,b,c):
            self.assertEqual(self.status(token)[0], 'expired')
        for container in containers:
            container.remove.assert_called_once_with(force=True, v=False)
        lab.docker_client.volumes.remove.assert_not_called()
        self.assertFalse(list(lab.CONFIG_DIR.glob('*.conf')))
        self.assertEqual(lab.session_capacity()['active_sessions'], 0)

    def test_docker_outage_does_not_expire_rows(self):
        token = 'a'*32
        self.row(token)
        lab.docker_client.containers.list.side_effect = lab.DockerException('offline')
        with self.assertRaises(lab.DockerException):
            lab.reconcile_sessions()
        self.assertEqual(self.status(token)[0], 'active')

    def test_bad_ownership_aborts_before_deletion(self):
        c = self.container('a'*32)
        c.name = 'unrelated-container'
        lab.docker_client.containers.list.return_value = [c]
        with self.assertRaisesRegex(RuntimeError, 'ownership'):
            lab.reconcile_sessions()
        c.remove.assert_not_called()

    def test_cleanup_failure_keeps_row_retryable(self):
        token = 'b'*32
        self.row(token)
        c = self.container(token, 'exited')
        c.remove.side_effect = lab.DockerException('busy')
        lab.docker_client.containers.list.return_value = [c]
        with self.assertRaises(lab.DockerException):
            lab.reconcile_sessions()
        self.assertEqual(self.status(token)[0], 'active')
        c.remove.side_effect = None
        lab.reconcile_sessions()
        self.assertEqual(self.status(token)[0], 'expired')


if __name__ == '__main__':
    unittest.main()
