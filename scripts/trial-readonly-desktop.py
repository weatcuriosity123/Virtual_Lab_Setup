#!/usr/bin/env python3
"""Twenty-minute disposable browser trial. No classroom or saved-home changes."""
import argparse
import json
import os
import secrets
import signal
import subprocess
import time


def run(*args, check=True, env=None):
    return subprocess.run(args, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, check=check, timeout=30, env=env)


def create_command(name, network, image):
    command = ['docker', 'create', '--name', name, '--network', network,
               '--publish', '127.0.0.1:13001:3001', '--read-only',
               '--memory', '1536m', '--memory-swap', '1536m', '--cpus', '4',
               '--pids-limit', '512', '--shm-size', '256m',
               '--cap-drop', 'NET_RAW', '--cap-drop', 'NET_ADMIN',
               '--security-opt', 'no-new-privileges:true',
               '--sysctl', 'net.ipv6.conf.all.disable_ipv6=1',
               '--log-driver', 'json-file', '--log-opt', 'max-size=2m',
               '--log-opt', 'max-file=1', '--env', 'CUSTOM_USER=student',
               '--env', 'PASSWORD', '--env', 'START_DOCKER=false',
               '--env', 'PUID=1000', '--env', 'PGID=1000', '--env', 'TZ=Asia/Kolkata']
    for mount in ['/config:rw,size=512m,mode=1777', '/run:rw,exec,size=64m,mode=755',
                  '/tmp:rw,exec,size=128m,mode=1777', '/var/log:rw,size=16m,mode=755',
                  '/var/lib/nginx:rw,size=32m,mode=755',
                  '/defaults:rw,size=16m,mode=700,uid=1000,gid=1000']:
        command += ['--tmpfs', mount]
    return command + [image]


READY = """import base64,os,subprocess,urllib.request
names=set(subprocess.check_output(['ps','-eo','comm'],text=True).split())
assert {'nginx','selkies','pulseaudio','Xvfb','xfce4-session'}<=names
request=urllib.request.Request('http://127.0.0.1:3000/')
request.add_header('Authorization','Basic '+base64.b64encode(('student:'+os.environ['PASSWORD']).encode()).decode())
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
assert opener.open(request,timeout=2).status==200
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='linux-lab:cse-readonly-candidate')
    args = parser.parse_args()
    if run('docker', 'ps', '-q', '--filter', 'label=linux-lab.managed=true').stdout.strip():
        raise SystemExit('End active classroom labs before this trial.')
    inspected = run('docker', 'image', 'inspect', args.image, check=False)
    if inspected.returncode:
        raise SystemExit('Build the read-only candidate first.')
    info = json.loads(inspected.stdout)[0]
    if set((info['Config'].get('Volumes') or {})) - {'/config'}:
        raise SystemExit('Unexpected image volume declarations; refusing trial.')
    name = 'linux-lab-browser-trial-' + secrets.token_hex(6)
    network = name + '-net'
    password = secrets.token_urlsafe(24)
    env = dict(os.environ, PASSWORD=password)
    # Names are random and owned exclusively by this invocation, including on CLI timeout.
    print('Trial container:', name, '\nTrial network:', network, flush=True)
    print('Keep this terminal open. Ctrl+C cleans up; maximum trial time is 20 minutes.', flush=True)
    print('Do not launch classroom labs during the trial.', flush=True)
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    attempted_network = attempted_container = False
    try:
        attempted_network = True
        run('docker', 'network', 'create', '--internal', network)
        attempted_container = True
        run(*create_command(name, network, info['Id']), env=env)
        run('docker', 'start', name)
        deadline = time.monotonic() + 120
        stable = 0
        while time.monotonic() < deadline:
            response = run('docker', 'exec', name, 'python3', '-c', READY, check=False)
            stable = stable + 1 if response.returncode == 0 else 0
            if stable == 3:
                break
            time.sleep(2)
        else:
            print(run('docker', 'logs', '--tail', '80', name, check=False).stdout)
            raise SystemExit('Desktop did not become ready; trial will be removed.')
        print('READY: open https://localhost:13001 through your Windows SSH tunnel.', flush=True)
        print('Username: student\nPassword: ' + password, flush=True)
        print('Fresh temporary home; no internet on this internal trial network.', flush=True)
        print('All files in this trial are deleted on cleanup. Ctrl+C when finished.', flush=True)
        deadline = time.monotonic() + 1200
        while time.monotonic() < deadline:
            time.sleep(2)
            if run('docker', 'inspect', '--format', '{{.State.Running}}', name).stdout.strip() != 'true':
                raise SystemExit('Trial container stopped unexpectedly.')
    except KeyboardInterrupt:
        print('\nEnding trial.')
    finally:
        cleanup_failed = False
        for attempted, command in [
            (attempted_container, ['docker', 'rm', '-f', '-v', name]),
            (attempted_network, ['docker', 'network', 'rm', network]),
        ]:
            if attempted:
                try:
                    result = run(*command, check=False)
                    if result.returncode:
                        cleanup_failed = True
                        print('Check cleanup manually:', ' '.join(command), '\n', result.stdout)
                except subprocess.TimeoutExpired:
                    cleanup_failed = True
                    print('Cleanup timed out. Run:', ' '.join(command))
        print('After cleanup: sudo python3 /usr/local/sbin/linux-lab-network-guard check')
        if cleanup_failed:
            raise SystemExit('Cleanup incomplete; resolve before launching classroom labs.')
        print('Trial removed. Classroom configuration and saved homes were not changed.')


if __name__ == '__main__':
    main()
