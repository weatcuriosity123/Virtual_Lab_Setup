#!/usr/bin/env python3
"""Offline diagnostic only: try VS Code with constrained namespace seccomp exceptions."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import tempfile
import time
import urllib.request

URL = 'https://raw.githubusercontent.com/moby/moby/v26.1.5/profiles/seccomp/default.json'
EXPECTED = '885442dc08f21f8d60f99ea43d59af88b1c529103815fe24bbf9ce998d3a609d'


def make_profile(data):
    encoded = json.dumps(data, sort_keys=True, separators=(',', ':')).encode()
    if hashlib.sha256(encoded).hexdigest() != EXPECTED:
        raise ValueError('Upstream profile differs from reviewed Docker 26.1.5 profile.')
    data = json.loads(encoded)
    data['syscalls'].append({'names': ['unshare'], 'action': 'SCMP_ACT_ALLOW',
                            'args': [{'index': 0, 'value': 268435456, 'op': 'SCMP_CMP_EQ'}]})
    # Chromium checks support with clone(NEWUSER | SIGCHLD), then launches
    # its sandbox with NEWUSER and optional NEWPID/NEWNET. The Pi trace also
    # showed the renderer fork requires exactly NEWPID | SIGCHLD.
    for flags in (0x10000000, 0x20000000, 0x30000000, 0x50000000, 0x70000000):
        data['syscalls'].append({
            'names': ['clone'], 'action': 'SCMP_ACT_ALLOW',
            'includes': {'arches': ['arm64', 'amd64']},
            'args': [{'index': 0, 'value': flags | 17, 'op': 'SCMP_CMP_EQ'}]
        })
    return data


def run(*args, check=True, timeout=30, env=None):
    return subprocess.run(args, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, check=check, timeout=timeout, env=env)


INSPECT = """import pathlib,json
root=pathlib.Path('/proc')
rows=[]
for p in root.iterdir():
    if not p.name.isdigit(): continue
    try:
        cmd=(p/'cmdline').read_bytes().replace(b'\\0',b' ').decode(errors='replace')
        if not cmd.startswith('/usr/share/code/'): continue
        status=dict(line.split(':',1) for line in (p/'status').read_text().splitlines() if ':' in line)
        ns={}
        for n in ('user','pid','net'):
            try: ns[n]=(p/'ns'/n).readlink().as_posix()
            except OSError: ns[n]='unreadable'
        rows.append({'pid':p.name,'command':cmd,'namespaces':ns,
                     'status':{k:status.get(k,'').strip() for k in ('Uid','NoNewPrivs','Seccomp','Seccomp_filters','CapEff')}})
    except (OSError,ValueError): continue
print(json.dumps(rows,indent=2))
"""


TRACE_SUMMARY = """from pathlib import Path
from collections import deque
files=sorted(Path('/tmp').glob('code-syscalls.*'))
print('Trace files:',len(files))
remaining=160
for path in files:
    with path.open(errors='replace') as stream:
        lines=deque((line.strip() for line in stream if any(k in line for k in ('EPERM','EACCES','EAGAIN','ENOMEM','ENOSPC','SIGSYS','clone(','clone3(','unshare('))),maxlen=40)
    if lines and remaining:
        print('---',path.name,'---')
        for line in list(lines)[-remaining:]:
            print(line[:1200]); remaining-=1
"""


def launch_command(trace):
    prefix = ('timeout --signal=TERM --kill-after=3s 15s '
              'strace -ff -tt -s 80 -e trace=process,unshare,setns,prctl,seccomp,chroot '
              '-o /tmp/code-syscalls ' if trace else '')
    return ('exec ' + prefix + 'code --disable-setuid-sandbox --disable-extensions --disable-gpu '
            '--user-data-dir=/config/code-sandbox-probe --verbose '
            '> /tmp/code-sandbox-probe.log 2>&1')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', action='store_true', help='Use separate debug image; tracing is diagnostic only')
    args = parser.parse_args()
    version = run('docker', 'version', '--format', '{{.Server.Version}}').stdout.strip()
    if not version.startswith('26.1.5'):
        raise SystemExit('This diagnostic profile was reviewed for Docker 26.1.5 only; found ' + version)
    if run('docker', 'ps', '-q', '--filter', 'label=linux-lab.managed=true').stdout.strip():
        raise SystemExit('End classroom labs first.')
    if run('docker', 'ps', '-q', '--filter', 'name=linux-lab-browser-trial-').stdout.strip():
        raise SystemExit('End the browser trial first.')
    spec = importlib.util.spec_from_file_location('trial', Path(__file__).with_name('trial-readonly-desktop.py'))
    trial = importlib.util.module_from_spec(spec); spec.loader.exec_module(trial)
    image = 'linux-lab:cse-readonly-debug' if args.trace else 'linux-lab:cse-readonly-candidate'
    info = json.loads(run('docker', 'image', 'inspect', image).stdout)[0]
    if set(info['Config'].get('Volumes') or {}) - {'/config'}:
        raise SystemExit('Unexpected declared image volumes.')
    with urllib.request.urlopen(URL, timeout=30) as response:
        profile = make_profile(json.load(response))
    name = 'linux-lab-code-probe-' + secrets.token_hex(6)
    def interrupted(*_): raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    with tempfile.TemporaryDirectory(prefix='linux-lab-code-profile-') as folder:
        path = Path(folder) / 'seccomp.json'; path.write_text(json.dumps(profile))
        command = trial.create_command(name, 'none', info['Id'])
        i = command.index('--publish'); del command[i:i+2]
        command[-1:-1] = ['--security-opt', 'seccomp=' + str(path)]
        attempted = False
        try:
            print('Disposable offline probe:', name, flush=True)
            attempted = True
            run(*command, env=dict(os.environ, PASSWORD=secrets.token_urlsafe(24)))
            run('docker', 'start', name)
            for _ in range(60):
                if run('docker', 'exec', name, 'python3', '-c', trial.READY, check=False, timeout=10).returncode == 0:
                    break
                time.sleep(2)
            else:
                print(run('docker', 'logs', '--tail', '60', name, check=False).stdout)
                raise SystemExit('Desktop prerequisite failed; VS Code not tested.')
            print('Namespace check as UID 1000:', flush=True)
            result = run('docker', 'exec', '--user', '1000:1000', name,
                         'unshare', '--user', '--map-root-user', '/usr/bin/id', check=False)
            print(result.stdout)
            if result.returncode: raise SystemExit('Namespace prerequisite failed.')
            run('docker', 'exec', '--detach', '--user', '1000:1000',
                '--env', 'HOME=/config', '--env', 'DISPLAY=:1', name, 'sh', '-c',
                launch_command(args.trace))
            print('Waiting 20 seconds for VS Code renderer startup...', flush=True)
            time.sleep(20)
            print('--- VS Code log ---')
            print(run('docker', 'exec', name, 'tail', '-n', '100', '/tmp/code-sandbox-probe.log', check=False).stdout)
            if args.trace:
                print('--- Selected process/namespace syscall trace ---')
                print(run('docker', 'exec', name, 'python3', '-c', TRACE_SUMMARY).stdout)
                print('DIAGNOSTIC ONLY: tracing can change sandbox behavior. No launch acceptance inferred.')
                return
            print('--- VS Code process and sandbox evidence ---')
            result = run('docker', 'exec', name, 'python3', '-c', INSPECT)
            print(result.stdout)
            rows = json.loads(result.stdout)
            if not any('--type=renderer' in row['command'] for row in rows):
                raise SystemExit('NOT READY: no surviving renderer observed. Review the startup error before changing policy.')
            print('Renderer observed. Sandbox evidence still requires review; this is NOT production acceptance.')
        finally:
            if attempted:
                result = run('docker', 'rm', '-f', '-v', name, check=False)
                if result.returncode:
                    print('CLEANUP FAILED. Run: docker rm -f -v ' + name)
                    raise SystemExit(1)
                print('Disposable container removed. Classroom policy and saved homes unchanged.')


if __name__ == '__main__':
    main()
