"""Backup integrity and failure-path tests; privileged host drill remains required."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('storage_backup', Path(__file__).resolve().parents[1] / 'scripts/storage-backup.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class BackupTests(unittest.TestCase):
    def fixture(self, root):
        (root / 'backend/data').mkdir(parents=True)
        (root / 'pool.img').write_bytes(b'fake image')
        (root / 'pool.uuid').write_text('test-uuid')
        for p in (root / 'homes.db', root / 'backend/data/sessions.db'):
            with sqlite3.connect(p) as db:
                db.execute('CREATE TABLE example (id INTEGER)')
        self.seal(root)

    def seal(self, root):
        (root / 'manifest.json').write_text(json.dumps({'format': 1, 'sha256': m.manifest(root)}))

    def test_checksum_and_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            m.verify(root)
            (root / 'pool.img').write_bytes(b'changed image')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                m.verify(root)

    def test_symlink_change_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            link = root / 'backend/link'
            link.symlink_to('first')
            self.seal(root)
            m.verify(root)
            link.unlink()
            link.symlink_to('second')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                m.verify(root)

    def test_database_corruption_detected_even_with_updated_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            (root / 'homes.db').write_bytes(b'not a sqlite database')
            self.seal(root)
            with self.assertRaises(sqlite3.DatabaseError):
                m.verify(root)

    def test_idle_refuses_stopped_containers(self):
        with patch.object(m, 'run', return_value='container-id'):
            with self.assertRaisesRegex(ValueError, 'stopped'):
                m.check_idle(Path('/unused'))

    def test_copy_failure_restarts_dependencies_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / 'state'
            state.mkdir()
            (state / 'pool.img').write_bytes(b'image')
            (state / 'pool.uuid').write_text('uuid')
            backend = root / 'backend'
            backend.mkdir()
            calls = []
            def fake_run(*args):
                calls.append(args)
                if args[:2] == ('systemctl', 'is-active'):
                    return 'active'
                if args[:2] == ('docker', 'inspect'):
                    return 'true'
                if args[0] == 'findmnt':
                    return json.dumps({'filesystems': [{'uuid': 'uuid', 'options': 'prjquota'}]})
                if args[0] == 'systemd-escape':
                    return 'pool.mount'
                if args[0] == 'cp':
                    raise OSError('disk write failed')
                return ''
            with patch.object(m, 'STATE', state), patch.object(m, 'run', side_effect=fake_run), patch.object(m, 'check_idle'), patch.object(m, 'check_homes'), patch.object(m.subprocess, 'run') as raw:
                raw.return_value.returncode = 1
                with self.assertRaisesRegex(OSError, 'disk write'):
                    m.backup(backend, root / 'backup')
            self.assertEqual(calls[-3:], [('systemctl', 'start', 'pool.mount'), ('systemctl', 'start', m.SERVICE), ('docker', 'start', 'linux-lab-api')])

    def test_drill_never_overwrites_existing_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'new recovery-test'):
                m.drill(Path(tmp), Path(tmp))

    def test_drill_unmounts_after_registry_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source'
            source.mkdir()
            self.fixture(source)
            calls = []
            def fake_run(*args):
                calls.append(args)
                return ''
            with patch.object(m, 'verify'), patch.object(m, 'run', side_effect=fake_run), patch.object(m, 'connect', side_effect=sqlite3.DatabaseError('broken registry')):
                with self.assertRaises(sqlite3.DatabaseError):
                    m.drill(source, Path(tmp) / 'restored')
            self.assertEqual(calls[-1][0], 'umount')
            self.assertIn('loop,ro,noload,nodev,nosuid,noexec', next(c for c in calls if c[0] == 'mount'))


if __name__ == '__main__':
    unittest.main()
