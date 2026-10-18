#!/usr/bin/env python3
"""Cold quota-pool backup and isolated, read-only recovery drill (single host)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import fcntl
from datetime import datetime, timezone

STATE = Path('/var/lib/linux-lab-storage')
POOL = Path('/srv/linux-lab-storage/pool')
SERVICE = 'linux-lab-storage.service'


def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout.strip()


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def connect(path):
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)


def check_db(path):
    with connect(path) as db:
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('Database integrity check failed: ' + str(path))


def check_idle(backend):
    if run('docker', 'ps', '-aq', '--filter', 'label=linux-lab.managed=true'):
        raise ValueError('End all labs first; even stopped student containers must be removed through normal cleanup.')
    with connect(backend / 'data/sessions.db') as db:
        if db.execute("SELECT COUNT(*) FROM sessions WHERE status IN ('active','starting')").fetchone()[0]:
            raise ValueError('Active or starting sessions remain. End them through the dashboard.')


def check_homes(backend):
    with connect(STATE / 'homes.db') as db:
        rows = db.execute('SELECT name,state FROM homes').fetchall()
    if any(state not in ('ready', 'deleted') for _, state in rows):
        raise ValueError('Finish pending home migration/deletion before backup.')
    known = {name for name, _ in rows}
    with connect(backend / 'data/sessions.db') as db:
        registered = {r[0] for r in db.execute('SELECT name FROM student_homes')}
    if registered - known:
        raise ValueError('Some registered homes are not in the quota registry. Migrate/resolve them first; legacy homes are not included.')


def manifest(folder):
    return {str(p.relative_to(folder)): ({'symlink': os.readlink(p)} if p.is_symlink() else {'sha256': digest(p)})
            for p in sorted(folder.rglob('*')) if (p.is_file() or p.is_symlink()) and p != folder / 'manifest.json'}


def verify(folder):
    data = json.loads((folder / 'manifest.json').read_text())
    if data.get('format') != 1 or manifest(folder) != data['sha256']:
        raise ValueError('Backup checksum or file inventory mismatch.')
    for name in ('pool.img', 'pool.uuid', 'homes.db', 'backend/data/sessions.db'):
        if name not in data['sha256'] or (folder / name).is_symlink() or not (folder / name).is_file():
            raise ValueError('Incomplete backup: ' + name)
    check_db(folder / 'homes.db')
    check_db(folder / 'backend/data/sessions.db')
    return data


def backup(backend, destination):
    backend = backend.resolve(strict=True)
    destination = destination.resolve()
    if destination.exists():
        raise ValueError('Choose a new backup directory; existing paths are never overwritten.')
    if any(destination.is_relative_to(p) for p in (backend, STATE, POOL)):
        raise ValueError('Backup must be outside the backend and storage directories.')
    if run('systemctl', 'is-active', SERVICE) != 'active':
        raise ValueError('Storage service must be healthy before backup.')
    if run('docker', 'inspect', '-f', '{{.State.Running}}', 'linux-lab-api') != 'true':
        raise ValueError('API must be running before backup.')
    mount = json.loads(run('findmnt', '--json', '--mountpoint', str(POOL), '-o', 'UUID,OPTIONS'))['filesystems'][0]
    if mount['uuid'] != (STATE / 'pool.uuid').read_text().strip() or 'prjquota' not in mount['options'].split(','):
        raise ValueError('Wrong storage pool mounted.')
    check_idle(backend)
    check_homes(backend)
    destination.parent.mkdir(parents=True, exist_ok=True)
    needed = (STATE / 'pool.img').stat().st_size + 1024**3
    if shutil.disk_usage(destination.parent).free < needed:
        raise ValueError('Need pool image size plus at least 1 GiB free at the backup destination.')
    unit = run('systemd-escape', '--path', '--suffix=mount', str(POOL))
    destination.mkdir(mode=0o700)
    print('Entering maintenance window; copying and hashing the pool may take several minutes.', flush=True)
    api_stopped = service_stopped = mount_stopped = False
    try:
        api_stopped = True
        run('docker', 'stop', 'linux-lab-api')
        check_idle(backend)  # Close the session-creation race after stopping the API.
        service_stopped = True
        run('systemctl', 'stop', SERVICE)
        check_homes(backend)
        mount_stopped = True
        run('systemctl', 'stop', unit)
        if subprocess.run(['findmnt', '-rn', '--mountpoint', str(POOL)], capture_output=True).returncode != 1:
            raise ValueError('Pool did not unmount; refusing a live image copy.')
        for name in ('pool.img', 'pool.uuid', 'homes.db'):
            run('cp', '--sparse=always', '--', str(STATE / name), str(destination / name))
        # Include any SQLite sidecars in the stopped registry snapshot.
        for path in STATE.glob('homes.db-*'):
            shutil.copy2(path, destination / path.name)
        target = destination / 'backend'
        target.mkdir()
        # Explicit runtime inputs; do not recurse into old deployment backups.
        for name in ('Dockerfile', 'requirements.txt', 'docker-compose.yml', 'docker-compose.override.yml', 'compose.network-isolation.yml', '.env'):
            if (backend / name).exists():
                shutil.copy2(backend / name, target / name)
        for path in backend.glob('*.py'):
            shutil.copy2(path, target / path.name)
        for name in ('data', 'frontend', 'nginx'):
            run('cp', '-a', '--', str(backend / name), str(target / name))
        shutil.copy2('/usr/local/sbin/linux-lab-storage-agent', destination / 'storage-agent.py')
        for optional, name in [('/etc/linux-lab-network.json', 'network-config.json'),
                               ('/usr/local/sbin/linux-lab-network-guard', 'network-guard.py'),
                               ('/var/lib/linux-lab-network/original.json', 'network-original.json')]:
            if Path(optional).exists():
                shutil.copy2(optional, destination / name)
        check_db(destination / 'homes.db')
        check_db(target / 'data/sessions.db')
        metadata = {'format': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
                    'scope': 'quota homes and application; excludes legacy volumes, Docker images and tunnel credentials',
                    'sha256': manifest(destination)}
        (destination / 'manifest.json').write_text(json.dumps(metadata, indent=2) + '\n')
        verify(destination)
        run('sync', '-f', str(destination))
        print('PASS: cold backup and checksums verified:', destination, flush=True)
    finally:
        # Dependencies restore in order; do not start the API if storage cannot start.
        if mount_stopped:
            run('systemctl', 'start', unit)
        if service_stopped:
            run('systemctl', 'start', SERVICE)
        if api_stopped:
            run('docker', 'start', 'linux-lab-api')
        print('Services restarted. Check service health and launch a lab.', flush=True)
    print('Backup contains student data and secrets. Keep it private and copy it off this disk.')


def drill(source, destination):
    source = source.resolve(strict=True)
    destination = destination.resolve()
    if destination.exists() or destination.is_relative_to(source) or any(destination.is_relative_to(p) for p in (STATE, POOL)):
        raise ValueError('Use a new recovery-test directory outside the backup and live storage.')
    print('Verifying backup before isolated recovery test...', flush=True)
    verify(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(destination.parent).free < (source / 'pool.img').stat().st_size + 1024**3:
        raise ValueError('Recovery test needs pool image size plus 1 GiB free.')
    destination.mkdir(mode=0o700)
    run('cp', '-a', '--sparse=always', '--', str(source) + '/.', str(destination))
    verify(destination)
    run('e2fsck', '-fn', str(destination / 'pool.img'))
    mountpoint = destination / 'recovered-homes'
    mountpoint.mkdir()
    mounted = False
    try:
        run('mount', '-o', 'loop,ro,noload,nodev,nosuid,noexec', str(destination / 'pool.img'), str(mountpoint))
        mounted = True
        with connect(destination / 'homes.db') as db:
            rows = db.execute('SELECT id,name,state FROM homes').fetchall()
        count = 0
        for project_id, name, state in rows:
            if not __import__('re').fullmatch(r'linux-lab-home-v1-[0-9a-f]{64}', name):
                raise ValueError('Invalid home name in registry.')
            home = mountpoint / name
            if state == 'ready':
                if home.is_symlink() or not home.is_dir():
                    raise ValueError('Registered home is missing from restored pool.')
                attrs = run('lsattr', '-pd', str(home)).split()
                if str(project_id + 10000) != attrs[0] or 'P' not in attrs[1]:
                    raise ValueError('Restored home project ID/inheritance mismatch.')
                count += 1
            elif state != 'deleted' or home.exists():
                raise ValueError('Unexpected incomplete/deleted home in restored pool.')
        print(f'PASS: isolated restore, image checksums, SQLite integrity, filesystem check and {count} home project IDs verified.')
    finally:
        if mounted:
            run('umount', str(mountpoint))
    print('Live storage was not changed. Test copy retained at:', destination)
    print('This drill does not start student desktops or replace a full disaster-recovery rehearsal.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['backup', 'drill', 'verify'])
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path, nargs='?')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Run with sudo; backups include private data.')
    os.umask(0o077)
    lock = open('/run/linux-lab-backup.lock', 'a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if args.operation == 'verify':
        verify(args.source)
        print('PASS: backup checksums and databases verified.')
    elif args.destination is None:
        parser.error('A new destination directory is required.')
    elif args.operation == 'backup':
        backup(args.source, args.destination)
    else:
        drill(args.source, args.destination)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, sqlite3.Error, subprocess.CalledProcessError) as exc:
        raise SystemExit('FAILED: ' + str(exc))
