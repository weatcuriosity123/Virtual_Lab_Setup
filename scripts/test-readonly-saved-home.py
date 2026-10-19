#!/usr/bin/env python3
"""Offline candidate test using one home copied from a verified cold backup."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import signal
import shutil
import subprocess
import tempfile
import time


def load(filename, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(*args, check=True, timeout=120, env=None):
    return subprocess.run([str(x) for x in args], check=check, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          timeout=timeout, env=env).stdout.strip()


def command(trial, name, image, home):
    args = trial.create_command(name, 'none', image)
    # This offline test has no published port and uses only the disposable copy.
    i = args.index('--publish'); del args[i:i+2]
    i = args.index('/config:rw,size=512m,mode=1777'); del args[i-1:i+1]
    args[-1:-1] = ['--mount', f'type=bind,src={home},dst=/config']
    return args


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup', type=Path)
    parser.add_argument('--home', help='Exact registered home name; required if backup has multiple homes')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo. This creates a disposable loop-mounted filesystem.')
    for tool in ['docker', 'rsync', 'fallocate', 'mkfs.ext4', 'mount', 'umount', 'mountpoint', 'chattr', 'setquota', 'repquota']:
        if not shutil.which(tool): raise SystemExit('Missing tool: ' + tool)
    backup = load('storage-backup.py', 'backup')
    trial = load('trial-readonly-desktop.py', 'trial')
    source = args.backup.resolve(strict=True)
    if source.is_relative_to(backup.STATE) or source.is_relative_to(backup.POOL):
        raise SystemExit('Use a cold backup directory, not live storage.')
    print('Verifying cold backup checksums; this can take several minutes.', flush=True)
    backup.verify(source)
    with backup.connect(source / 'homes.db') as db:
        names = [r[0] for r in db.execute("SELECT name FROM homes WHERE state='ready'")]
    selected = args.home or (names[0] if len(names) == 1 else None)
    if selected not in names or not re.fullmatch(r'linux-lab-home-v1-[0-9a-f]{64}', selected or ''):
        raise SystemExit('Select one home using --home. Ready homes:\n' + '\n'.join(names))
    info = json.loads(run('docker', 'image', 'inspect', 'linux-lab:cse-readonly-candidate'))[0]
    if set(info['Config'].get('Volumes') or {}) - {'/config'}:
        raise SystemExit('Unexpected declared image volumes.')
    if shutil.disk_usage('/var/tmp').free < 4 * 1024**3:
        raise SystemExit('Need at least 4 GiB free in /var/tmp for this 2 GiB disposable disk.')
    if run('docker', 'ps', '-aq', '--filter', 'label=linux-lab.managed=true'):
        raise SystemExit('End classroom labs first, including normal cleanup of stopped sessions.')
    if run('docker', 'ps', '-q', '--filter', 'name=linux-lab-browser-trial-'):
        raise SystemExit('Finish the browser trial first.')
    root = Path(tempfile.mkdtemp(prefix='linux-lab-home-probe-', dir='/var/tmp'))
    original, pool = root / 'original', root / 'pool'
    original.mkdir(); pool.mkdir()
    home = pool / 'home'
    container = None
    restart_api = False
    cleanup_ok = True
    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    print('Temporary test directory:', root, flush=True)
    print('API admissions paused during the test; keep this terminal open.', flush=True)
    try:
        if run('docker', 'inspect', '-f', '{{.State.Running}}', 'linux-lab-api') == 'true':
            restart_api = True
            run('docker', 'stop', 'linux-lab-api')
        if run('docker', 'ps', '-aq', '--filter', 'label=linux-lab.managed=true'):
            raise RuntimeError('A classroom lab appeared; end it normally and retry.')
        run('mount', '-o', 'loop,ro,noload,nodev,nosuid,noexec', source / 'pool.img', original)
        saved = original / selected
        if saved.is_symlink() or not saved.is_dir(): raise RuntimeError('Invalid backup home.')
        run('fallocate', '-l', '2G', root / 'test.img')
        run('mkfs.ext4', '-q', '-F', '-m', '0', '-O', 'quota,project', '-E', 'quotatype=prjquota', root / 'test.img')
        run('mount', '-t', 'ext4', '-o', 'loop,prjquota,nodev,nosuid', root / 'test.img', pool)
        home.mkdir()
        run('chattr', '-p', '42001', '+P', home)
        run('setquota', '-P', '42001', '0', '1048576', '0', '100000', pool)
        run('rsync', '-aH', '--numeric-ids', '--', str(saved) + '/', str(home) + '/', timeout=600)
        differences = run('rsync', '-aHnci', '--numeric-ids', '--', str(saved) + '/', str(home) + '/', timeout=600)
        if differences: raise RuntimeError('Copied home verification failed; candidate not started.')
        if home.stat().st_uid != 1000: raise RuntimeError('Saved home root is not UID 1000; no ownership changes attempted.')
        print('PASS: backup home copied and checksum/metadata comparison passed.', flush=True)
        # An independent project on the SAME test filesystem tests hard-limit enforcement.
        quota = pool / 'quota-check'; quota.mkdir(); os.chown(quota, 1000, 1000)
        run('chattr', '-p', '42002', '+P', quota)
        run('setquota', '-P', '42002', '0', '4096', '0', '0', pool)
        # Test from a container below so the private host parent remains mode 0700.
        marker = '.readonly-acceptance-' + secrets.token_hex(8)
        password = secrets.token_urlsafe(24)
        for iteration in (1, 2):
            container = 'linux-lab-home-probe-' + secrets.token_hex(6)
            cmd = command(trial, container, info['Id'], home)
            cmd[-1:-1] = ['--mount', f'type=bind,src={quota},dst=/quota-check']
            run(*cmd, env=dict(os.environ, PASSWORD=password))
            run('docker', 'start', container)
            ready = False
            for _ in range(60):
                try:
                    run('docker', 'exec', container, 'python3', '-c', trial.READY, timeout=10)
                    ready = True; break
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired): time.sleep(2)
            if not ready:
                print(run('docker', 'logs', '--tail', '80', container, check=False))
                raise RuntimeError('Copied-home desktop failed readiness.')
            code = """import pathlib,errno,os
assert os.getuid()==1000
p=pathlib.Path('/config')/os.environ['PROBE_MARKER']
if os.environ['PROBE_ROUND']=='1': p.write_text('persistent marker\\n')
assert p.read_text()=='persistent marker\\n'
try:
    with open('/quota-check/full','wb') as f:
        for _ in range(8): f.write(b'x'*1048576)
except OSError as e: assert e.errno==errno.EDQUOT,e
else: raise AssertionError('Quota limit not enforced')
finally: pathlib.Path('/quota-check/full').unlink(missing_ok=True)
"""
            run('docker', 'exec', '--user', '1000:1000', '--env', 'PROBE_MARKER=' + marker,
                '--env', 'PROBE_ROUND=' + str(iteration), container, 'python3', '-c', code)
            print(f'PASS: copied-home desktop start {iteration}, UID 1000 writes and hard quota enforcement.', flush=True)
            run('docker', 'rm', '-f', '-v', container); container = None
        print(run('repquota', '-P', pool))
        print('PASS: saved marker survived container recreation. Original backup and live homes unchanged.')
        print('Portal usage banner, latest live-home changes and VS Code sandbox remain separate acceptance checks.')
    finally:
        if container:
            try: run('docker', 'rm', '-f', '-v', container)
            except Exception:
                cleanup_ok = False
                print('Remove test container manually:', container)
        for path in (pool, original):
            if subprocess.run(['mountpoint', '-q', str(path)]).returncode == 0:
                try: run('umount', path)
                except Exception:
                    cleanup_ok = False
                    print('Unmount manually after removing test container:', path)
        if cleanup_ok: shutil.rmtree(root)
        else: print('Temporary data retained:', root)
        if restart_api: run('docker', 'start', 'linux-lab-api')
        if not cleanup_ok: raise SystemExit('Cleanup incomplete. Do not remove mounted directories.')
        print('Temporary disk removed; API restored if it was previously running.')


if __name__ == '__main__':
    main()
