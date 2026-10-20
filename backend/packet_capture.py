"""Bounded packet capture in a verified session's network namespace."""
import base64
import threading
from datetime import datetime, timezone

import docker
from docker.errors import DockerException, NotFound
from fastapi import HTTPException

LABEL = 'linux-lab.capture'
PATH = '/tmp/capture-check.pcapng'
MAX_BYTES = 300 * 1024
HELPER_CODE = '''import base64, subprocess, sys
p = subprocess.run(['/usr/bin/dumpcap', '-i', 'eth0', '-p', '-a', 'duration:10',
                    '-a', 'filesize:256', '-c', '2000', '-s', '256', '-w', '-'],
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
if p.returncode or not (12 <= len(p.stdout) <= 300 * 1024):
    sys.exit(1)
sys.stdout.write(base64.b64encode(p.stdout).decode('ascii'))
'''
_lock = threading.Lock()
_busy = set()
_slots = threading.BoundedSemaphore(2)


def cleanup(client, token=None):
    labels = [LABEL + '=true']
    if token is not None:
        labels.append('linux-lab.capture.session=' + token)
    for helper in client.containers.list(all=True, filters={'label': labels}):
        try:
            helper.remove(force=True, v=True)
        except NotFound:
            pass


def capture(client, row):
    token = row['token']
    with _lock:
        if token in _busy:
            raise HTTPException(409, 'A capture is already running for this lab.')
        if not _slots.acquire(blocking=False):
            raise HTTPException(429, 'Capture service is busy. Retry shortly.')
        _busy.add(token)
    helper = None
    try:
        if (row['status'] != 'active' or
                datetime.fromisoformat(row['expires_at']) <= datetime.now(timezone.utc)):
            raise HTTPException(409, 'Start an active lab before capturing traffic.')
        desktop = client.containers.get(row['container_name'])
        desktop.reload()
        if (desktop.status != 'running' or
                desktop.name != 'linux-lab-session-' + token or
                desktop.labels.get('linux-lab.session') != token or
                desktop.labels.get('linux-lab.managed') != 'true'):
            raise HTTPException(409, 'Lab container ownership or state mismatch.')
        check = desktop.exec_run(
            ['sh', '-c', 'test -x /usr/bin/dumpcap && command -v python3 && test -w /tmp'],
            user='1000:1000')
        if check.exit_code:
            raise HTTPException(409, 'This template needs dumpcap, Python 3 and writable /tmp.')
        helper = client.containers.run(
            image=desktop.image.id, name='linux-lab-capture-' + token,
            entrypoint='python3', command=['-c', HELPER_CODE],
            network_mode='container:' + desktop.id,
            user='0:0', cap_drop=['ALL'], cap_add=['NET_RAW'],
            security_opt=['no-new-privileges:true'], read_only=True,
            tmpfs={'/tmp': 'rw,nosuid,nodev,size=16m'},
            mem_limit='128m', memswap_limit='128m', pids_limit=32, nano_cpus=500_000_000,
            log_config=docker.types.LogConfig(type='json-file', config={'max-size': '1m', 'max-file': '1'}),
            labels={LABEL: 'true', 'linux-lab.capture.session': token}, detach=True)
        result = helper.wait(timeout=25)
        if result.get('StatusCode') != 0:
            raise HTTPException(503, 'Packet capture failed. Contact the administrator.')
        encoded = helper.logs(stdout=True, stderr=False)
        if len(encoded) > 4 * ((MAX_BYTES + 2) // 3):
            raise HTTPException(503, 'Capture output exceeded its size limit.')
        # Docker's JSON logs are text: transport the pcapng as ASCII, not raw bytes.
        data = base64.b64decode(encoded, validate=True)
        if not (12 <= len(data) <= MAX_BYTES) or data[:4] != b'\x0a\x0d\x0d\x0a':
            raise HTTPException(503, 'Capture output was invalid or exceeded its size limit.')
        desktop.reload()
        if desktop.status != 'running':
            raise HTTPException(409, 'The lab ended during capture.')
        # exec writes into writable /tmp; Docker archive upload fails on read-only roots.
        # Fixed path, unprivileged writer, and O_NOFOLLOW prevent symlink traversal.
        for offset in range(0, len(data), 24000):
            chunk = base64.b64encode(data[offset:offset + 24000]).decode('ascii')
            mode = 'os.O_TRUNC' if offset == 0 else 'os.O_APPEND'
            script = (
                'import os,base64; '
                f'fd=os.open({PATH!r},os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK|{mode},0o600); '
                'import stat; assert stat.S_ISREG(os.fstat(fd).st_mode); '
                f'f=os.fdopen(fd,"wb"); f.write(base64.b64decode({chunk!r})); f.close()')
            write = desktop.exec_run(['python3', '-c', script], user='1000:1000')
            if write.exit_code:
                raise HTTPException(503, 'Could not save capture. Check /tmp/capture-check.pcapng permissions.')
        return {'path': PATH, 'bytes': len(data), 'duration_limit_seconds': 10}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, 'Capture unavailable. The lab may have ended; retry in an active lab.') from exc
    finally:
        try:
            if helper is not None:
                helper.remove(force=True, v=True)
        except DockerException:
            # Bounded dumpcap exits independently; startup/termination retries removal.
            pass
        finally:
            with _lock:
                _busy.discard(token)
                _slots.release()
