"""Capture isolation and cleanup checks; live Docker acceptance remains required."""
import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import packet_capture as capture
from fastapi import HTTPException


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.token = 'a' * 32
        self.row = dict(token=self.token, status='active',
                        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                        container_name='linux-lab-session-' + self.token)
        self.client = MagicMock()
        self.desktop = self.client.containers.get.return_value
        self.desktop.name = self.row['container_name']
        self.desktop.id = 'desktop-id'
        self.desktop.status = 'running'
        self.desktop.labels = {'linux-lab.session': self.token, 'linux-lab.managed': 'true'}
        self.desktop.image.id = 'sha256:tested-image'
        self.desktop.exec_run.return_value.exit_code = 0
        self.helper = self.client.containers.run.return_value
        self.helper.wait.return_value = {'StatusCode': 0}
        self.payload = b'\x0a\x0d\x0d\x0a' + bytes(range(256)) * 100
        self.helper.logs.return_value = base64.b64encode(self.payload)

    def test_success_isolated_bounded_and_unprivileged_write(self):
        result = capture.capture(self.client, self.row)
        self.assertEqual(result['bytes'], len(self.payload))
        options = self.client.containers.run.call_args.kwargs
        self.assertEqual(options['network_mode'], 'container:desktop-id')
        self.assertEqual(options['image'], 'sha256:tested-image')
        self.assertEqual(options['cap_add'], ['NET_RAW'])
        self.assertEqual(options['cap_drop'], ['ALL'])
        self.assertTrue(options['read_only'])
        self.assertNotIn('volumes', options)
        self.assertNotIn('privileged', options)
        self.assertEqual(options['mem_limit'], '128m')
        self.assertEqual(options['pids_limit'], 32)
        for call in self.desktop.exec_run.call_args_list:
            self.assertEqual(call.kwargs['user'], '1000:1000')
        self.helper.remove.assert_called_once_with(force=True, v=True)

    def test_expired_and_wrong_container_never_capture(self):
        self.row['expires_at'] = (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        with self.assertRaises(HTTPException):
            capture.capture(self.client, self.row)
        self.client.containers.run.assert_not_called()
        self.row['expires_at'] = (datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat()
        self.desktop.labels['linux-lab.session'] = 'b' * 32
        with self.assertRaises(HTTPException):
            capture.capture(self.client, self.row)
        self.client.containers.run.assert_not_called()

    def test_failed_capture_and_write_remove_helper(self):
        self.helper.wait.return_value = {'StatusCode': 1}
        with self.assertRaises(HTTPException):
            capture.capture(self.client, self.row)
        self.helper.remove.assert_called_once()
        self.assertNotIn(self.token, capture._busy)

    def test_invalid_or_oversized_payload_not_written(self):
        for payload in (b'not base64!', base64.b64encode(b'x' * (capture.MAX_BYTES + 1))):
            self.desktop.exec_run.reset_mock()
            self.helper.logs.return_value = payload
            with self.assertRaises(HTTPException):
                capture.capture(self.client, self.row)
            self.assertEqual(self.desktop.exec_run.call_count, 1)  # preflight only

    def test_timeout_and_write_failure_release_resources(self):
        self.helper.wait.side_effect = TimeoutError('timeout')
        with self.assertRaises(HTTPException):
            capture.capture(self.client, self.row)
        self.helper.remove.assert_called_once()
        self.assertNotIn(self.token, capture._busy)
        self.helper.wait.side_effect = None
        self.desktop.exec_run.side_effect = [MagicMock(exit_code=0), MagicMock(exit_code=1)]
        with self.assertRaises(HTTPException):
            capture.capture(self.client, self.row)
        self.assertEqual(self.helper.remove.call_count, 2)
        self.assertNotIn(self.token, capture._busy)

    def test_duplicate_denied(self):
        capture._busy.add(self.token)
        try:
            with self.assertRaises(HTTPException) as result:
                capture.capture(self.client, self.row)
            self.assertEqual(result.exception.status_code, 409)
            self.client.containers.run.assert_not_called()
        finally:
            capture._busy.remove(self.token)

    def test_cleanup_selects_only_capture_helpers(self):
        capture.cleanup(self.client, self.token)
        self.client.containers.list.assert_called_once_with(all=True, filters={'label': [
            'linux-lab.capture=true', 'linux-lab.capture.session=' + self.token]})


if __name__ == '__main__':
    unittest.main()
