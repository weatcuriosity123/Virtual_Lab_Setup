#!/usr/bin/env python3
"""Disposable network-policy test. Never attaches to the live lab network."""
import ipaddress
import json
import os
import socket
import subprocess
import threading
import time

NETWORK = 'linux-lab-isolation-test'
BRIDGE = 'll-isotest'
CHAIN = 'LL_ISOTEST'
SUBNET = ipaddress.ip_network('172.30.250.0/24')
NAMES = ['ll-isotest-student-a', 'll-isotest-student-b', 'll-isotest-proxy']
IMAGE = 'backend-api'
BLOCKED = ['0.0.0.0/8', '10.0.0.0/8', '100.64.0.0/10', '127.0.0.0/8',
           '169.254.0.0/16', '172.16.0.0/12', '192.168.0.0/16',
           '198.18.0.0/15', '224.0.0.0/4', '240.0.0.0/4']


def run(*args, check=True, timeout=45):
    return subprocess.run(args, check=check, text=True, capture_output=True, timeout=timeout)


def tcp(container, address, port, expected):
    code = '''import socket,sys
try:
 s=socket.create_connection((sys.argv[1],int(sys.argv[2])),timeout=2);s.close()
except OSError:
 sys.exit(3)
'''
    result = run('docker', 'exec', container, 'python3', '-c', code, address, str(port), check=False)
    if result.returncode not in (0, 3):
        raise RuntimeError('Probe failed to execute: ' + result.stderr)
    if (result.returncode == 0) != expected:
        raise RuntimeError(f'Unexpected TCP result: {container} -> {address}:{port}, expected reachable={expected}')


def preflight():
    if os.geteuid() != 0:
        raise RuntimeError('Run with sudo on the Docker host.')
    run('docker', 'image', 'inspect', IMAGE)
    if run('docker', 'network', 'inspect', NETWORK, check=False).returncode == 0:
        raise RuntimeError('Test network already exists; inspect leftover resources before retrying.')
    if run('ip', 'link', 'show', BRIDGE, check=False).returncode == 0:
        raise RuntimeError('Test bridge name is already in use.')
    for name in NAMES:
        if run('docker', 'container', 'inspect', name, check=False).returncode == 0:
            raise RuntimeError('Test container name is already in use: ' + name)
    for tool in ('iptables', 'ip6tables'):
        run(tool, '--version')
        if run(tool, '-w', '5', '-S', CHAIN, check=False).returncode == 0:
            raise RuntimeError('Test firewall chain already exists: ' + tool)
    run('iptables', '-w', '5', '-S', 'DOCKER-USER')
    for key in ('net.bridge.bridge-nf-call-iptables', 'net.bridge.bridge-nf-call-ip6tables'):
        if run('sysctl', '-n', key).stdout.strip() != '1':
            raise RuntimeError('Bridge filtering must already be enabled: ' + key)
    for family in ('-4',):
        for route in json.loads(run('ip', '-j', family, 'route', 'show', 'table', 'all').stdout):
            dest = route.get('dst', 'default')
            if dest != 'default' and ipaddress.ip_network(dest, strict=False).overlaps(SUBNET):
                raise RuntimeError('Test subnet overlaps a host route: ' + dest)
    ids = run('docker', 'network', 'ls', '-q').stdout.split()
    if ids:
        for network in json.loads(run('docker', 'network', 'inspect', *ids).stdout):
            for config in network.get('IPAM', {}).get('Config') or []:
                if config.get('Subnet'):
                    net = ipaddress.ip_network(config['Subnet'])
                    if net.version == 4 and net.overlaps(SUBNET):
                        raise RuntimeError('Test subnet overlaps a Docker network.')


def main():
    preflight()
    created = []
    chains = []
    hooks = []
    network_created = False
    server = None
    try:
        run('docker', 'network', 'create', '--driver', 'bridge', '--subnet', str(SUBNET),
            '--gateway', '172.30.250.1', '--opt', 'com.docker.network.bridge.name=' + BRIDGE,
            '--label', 'linux-lab.isolation-test=true', NETWORK)
        network_created = True
        for name, ip in zip(NAMES, ['172.30.250.128', '172.30.250.129', '172.30.250.2']):
            run('docker', 'create', '--name', name, '--network', NETWORK, '--ip', ip,
                '--label', 'linux-lab.isolation-test=true', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges:true', '--read-only', '--user', '65534:65534',
                '--memory', '64m', '--pids-limit', '32', '--sysctl', 'net.ipv6.conf.all.disable_ipv6=1',
                '--entrypoint', 'python3', IMAGE, '-m', 'http.server', '3000', '--bind', '0.0.0.0')
            created.append(name)
            run('docker', 'start', name)
        for attempt in range(20):
            try:
                tcp(NAMES[0], '172.30.250.129', 3000, True)
                tcp(NAMES[0], '172.30.250.2', 3000, True)
                break
            except RuntimeError:
                if attempt == 19:
                    raise
                time.sleep(0.25)
        # A known reachable host listener makes the host-block test meaningful.
        server = socket.socket()
        server.bind(('172.30.250.1', 0))
        server.listen(16)
        port = server.getsockname()[1]
        def accept_connections():
            while True:
                try:
                    connection, _ = server.accept()
                    connection.close()
                except OSError:
                    return
        threading.Thread(target=accept_connections, daemon=True).start()
        tcp(NAMES[0], '172.30.250.1', port, True)
        print('PASS: peer, simulated control service and host listener reachable before filtering.', flush=True)
        for tool in ('iptables', 'ip6tables'):
            run(tool, '-w', '5', '-N', CHAIN)
            chains.append(tool)
        def rule(*args):
            run('iptables', '-w', '5', '-A', CHAIN, *args)
        # No prior student sessions are on this disposable bridge. Established
        # replies preserve proxy/API-initiated desktop TCP connections.
        rule('-m', 'conntrack', '--ctstate', 'INVALID', '-j', 'DROP')
        rule('-m', 'conntrack', '--ctstate', 'ESTABLISHED,RELATED', '-j', 'RETURN')
        rule('-s', '172.30.250.2', '-d', str(SUBNET), '-p', 'tcp', '--dport', '3000', '-j', 'RETURN')
        for subnet in BLOCKED:
            rule('-d', subnet, '-j', 'REJECT')
        rule('-j', 'RETURN')
        run('ip6tables', '-w', '5', '-A', CHAIN, '-j', 'DROP')
        # INPUT is distinct from Docker's forwarded-traffic path. Rules apply only
        # to our new bridge; host SSH on wlan0 and production bridges are untouched.
        for tool, parent, target in [('iptables', 'DOCKER-USER', CHAIN),
                                      ('iptables', 'INPUT', 'DROP'),
                                      ('ip6tables', 'FORWARD', CHAIN),
                                      ('ip6tables', 'INPUT', CHAIN)]:
            args = ('-i', BRIDGE, '-j', target)
            run(tool, '-w', '5', '-I', parent, '1', *args)
            hooks.append((tool, parent, args))
        tcp(NAMES[0], '172.30.250.129', 3000, False)
        tcp(NAMES[0], '172.30.250.2', 3000, False)
        tcp(NAMES[0], '172.30.250.1', port, False)
        tcp(NAMES[2], '172.30.250.128', 3000, True)
        tcp(NAMES[2], '172.30.250.129', 3000, True)
        print('PASS: student peer/control/host connections blocked; proxy-initiated desktop TCP works.', flush=True)
        for name in NAMES[:2]:
            run('docker', 'exec', name, 'python3', '-c',
                'from urllib.request import urlopen; r=urlopen("https://example.com", timeout=15); assert r.status==200', timeout=25)
            run('docker', 'exec', name, 'python3', '-c',
                'from pathlib import Path; assert Path("/proc/sys/net/ipv6/conf/all/disable_ipv6").read_text().strip()=="1"')
        print('PASS: DNS/HTTPS internet access works and student IPv6 is disabled.', flush=True)
        print(run('iptables', '-w', '5', '-L', CHAIN, '-n', '-v').stdout, flush=True)
        print('PASS: disposable network policy test completed. Production labs are NOT isolated yet.', flush=True)
    finally:
        if server:
            server.close()
        errors = []
        # Never remove protection while test containers remain connected.
        for name in reversed(created):
            result = run('docker', 'rm', '-f', name, check=False)
            if result.returncode:
                errors.append(result.stderr)
        if not errors:
            for tool, parent, args in reversed(hooks):
                result = run(tool, '-w', '5', '-D', parent, *args, check=False)
                if result.returncode:
                    errors.append(result.stderr)
            for tool in reversed(chains):
                for action in ('-F', '-X'):
                    result = run(tool, '-w', '5', action, CHAIN, check=False)
                    if result.returncode:
                        errors.append(result.stderr)
            if network_created:
                result = run('docker', 'network', 'rm', NETWORK, check=False)
                if result.returncode:
                    errors.append(result.stderr)
        if errors:
            raise RuntimeError('Cleanup needs attention; inspect test resources:\n' + '\n'.join(errors))
        else:
            print('Disposable containers, network and test firewall rules removed.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        raise SystemExit('FAILED: ' + str(exc) + '\n' + (getattr(exc, 'stderr', '') or ''))
