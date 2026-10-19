#!/usr/bin/env python3
"""Twenty-minute disposable browser trial. No classroom or saved-home changes."""
import argparse
import base64
import importlib.util
import ipaddress
from pathlib import Path
import ssl
import tempfile
import urllib.request
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
    parser.add_argument('--vscode-sandbox', action='store_true', help='Private trial of tested namespace policy and VS Code launch')
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
    profile_dir = None
    probe = None
    try:
        command = create_command(name, network, info['Id'])
        i = command.index('--publish'); del command[i:i+2]
        if args.vscode_sandbox:
            if not run('docker', 'version', '--format', '{{.Server.Version}}').stdout.strip().startswith('26.1.5'):
                raise SystemExit('Sandbox trial supports reviewed Docker 26.1.5 only.')
            spec = importlib.util.spec_from_file_location('code_probe', Path(__file__).with_name('test-vscode-sandbox.py'))
            probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
            with urllib.request.urlopen(probe.URL, timeout=30) as response:
                profile = probe.make_profile(json.load(response))
            profile_dir = tempfile.TemporaryDirectory(prefix='linux-lab-browser-profile-')
            profile_path = Path(profile_dir.name) / 'seccomp.json'
            profile_path.write_text(json.dumps(profile))
            command[-1:-1] = ['--security-opt', 'seccomp=' + str(profile_path)]
        attempted_network = True
        run('docker', 'network', 'create', '--internal', network)
        attempted_container = True
        run(*command, env=env)
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
        details = json.loads(run('docker', 'inspect', name).stdout)[0]
        address = str(ipaddress.IPv4Address(details['NetworkSettings']['Networks'][network]['IPAddress']))
        request = urllib.request.Request('https://' + address + ':3001/')
        request.add_header('Authorization', 'Basic ' + base64.b64encode(('student:' + password).encode()).decode())
        # Self-signed certificate on a newly created, local test container.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                   urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
        with opener.open(request, timeout=5) as response:
            if response.status != 200: raise RuntimeError('Host-to-desktop HTTPS check failed.')
        if probe:
            run('docker', 'exec', '--detach', '--user', '1000:1000',
                '--env', 'HOME=/config', '--env', 'DISPLAY=:1', name, 'sh', '-c', probe.launch_command(False))
            print('Starting VS Code with the tested namespace policy...', flush=True)
            time.sleep(20)
            evidence = run('docker', 'exec', name, 'python3', '-c', probe.INSPECT).stdout
            rows = json.loads(evidence)
            renderers = [r for r in rows if '--type=renderer' in r['command']]
            if not renderers:
                print(run('docker', 'exec', name, 'tail', '-n', '60', '/tmp/code-sandbox-probe.log', check=False).stdout)
                raise SystemExit('No renderer observed; browser trial stopped.')
            print('Renderer status:', json.dumps([r['status'] for r in renderers]), flush=True)
        print('READY: host-to-container HTTPS passed. Open a second Windows terminal:', flush=True)
        print('ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:13001:' + address + ':3001 YOUR_PI_USER@YOUR_PI_HOST', flush=True)
        print('Replace YOUR_PI_USER@YOUR_PI_HOST with your usual Pi SSH login.', flush=True)
        print('Open https://localhost:13001 in your Windows browser.', flush=True)
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
        if profile_dir:
            profile_dir.cleanup()
        print('After cleanup: sudo python3 /usr/local/sbin/linux-lab-network-guard check')
        if cleanup_failed:
            raise SystemExit('Cleanup incomplete; resolve before launching classroom labs.')
        print('Trial removed. Classroom configuration and saved homes were not changed.')


if __name__ == '__main__':
    main()
