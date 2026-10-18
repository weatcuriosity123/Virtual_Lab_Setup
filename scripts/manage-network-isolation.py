#!/usr/bin/env python3
"""Install or roll back the single-host quota-pilot network policy, with labs ended."""
import argparse
import fcntl
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess

ROOT=Path(__file__).resolve().parents[1]
STATE=Path('/var/lib/linux-lab-network')
SERVICE='linux-lab-network.service'
COMPOSE='docker-compose.yml:docker-compose.override.yml:compose.network-isolation.yml'


def run(*args,check=True):
    return subprocess.run(args,check=check,text=True,capture_output=True,timeout=180)


def idle(backend):
    if run('docker','ps','-aq','--filter','label=linux-lab.managed=true').stdout.strip():
        raise RuntimeError('End all labs first; managed containers still exist.')
    with sqlite3.connect((backend/'data/sessions.db').as_uri()+'?mode=ro',uri=True) as db:
        if db.execute("SELECT COUNT(*) FROM sessions WHERE status IN ('active','starting')").fetchone()[0]:
            raise RuntimeError('Active/starting database sessions remain. End them through the dashboard.')


def env_values(path):
    return dict(line.split('=',1) for line in path.read_text().splitlines() if '=' in line and not line.startswith('#'))


def write_env(path,values):
    lines=[line for line in path.read_text().splitlines() if line.split('=',1)[0] not in values]
    lines += [key+'='+value for key,value in values.items() if value is not None]
    path.write_text('\n'.join(lines)+'\n')


def install(backend):
    idle(backend)
    if 'network_guard.container_options' not in (backend/'main.py').read_text():
        raise RuntimeError('Deploy the updated API with install-classrooms.sh first.')
    override=backend/'docker-compose.override.yml'
    if not override.exists() or not override.read_text().startswith('# Managed by linux-lab quota installer'):
        raise RuntimeError('This installer requires the existing managed quota override; custom Compose needs review.')
    env=env_values(backend/'.env')
    if env.get('COMPOSE_FILE') not in (None,COMPOSE):
        raise RuntimeError('Custom COMPOSE_FILE requires manual review.')
    spec=importlib.util.spec_from_file_location('guard',ROOT/'host/network_guard.py')
    guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
    config=Path('/etc/linux-lab-network.json')
    fragment=backend/'compose.network-isolation.yml'
    first=not (STATE/'original.json').exists()
    if first and (config.exists() or fragment.exists()):
        raise RuntimeError('Existing unmanaged isolation config requires review.')
    if not first and json.loads((STATE/'original.json').read_text())['backend']!=str(backend):
        raise RuntimeError('Isolation is registered to another backend directory.')
    # Exclude every existing non-default routed IPv4 subnet from student egress.
    routes=[]
    for row in json.loads(run('ip','-j','-4','route','show','table','all').stdout):
        dest=row.get('dst','default')
        if dest=='default': continue
        net=ipaddress.ip_network(dest,strict=False)
        if row.get('dev')==guard.BRIDGE: continue
        if net.overlaps(ipaddress.ip_network(guard.SUBNET)):
            raise RuntimeError('Student subnet overlaps host route: '+str(net))
        routes.append(str(net))
    net_result=run('docker','network','inspect',guard.NETWORK,check=False)
    if net_result.returncode:
        ids=run('docker','network','ls','-q').stdout.split()
        for n in json.loads(run('docker','network','inspect',*ids).stdout) if ids else []:
            for entry in n.get('IPAM',{}).get('Config') or []:
                if entry.get('Subnet'):
                    net=ipaddress.ip_network(entry['Subnet'])
                    if net.version==4 and net.overlaps(ipaddress.ip_network(guard.SUBNET)):
                        raise RuntimeError('Student subnet overlaps Docker network.')
    else:
        guard.check_network(False)
    STATE.mkdir(mode=0o700,parents=True,exist_ok=True)
    if first:
        original={'backend':str(backend),'env':{k:env.get(k) for k in ('COMPOSE_FILE','DOCKER_NETWORK','LAB_NETWORK_ISOLATION')}}
        (STATE/'original.json').write_text(json.dumps(original))
    run('docker','stop','linux-lab-api')
    idle(backend)  # Check again after closing admission; leave API stopped on failure.
    if net_result.returncode:
        run('docker','network','create','--driver','bridge','--subnet',guard.SUBNET,
            '--ip-range',guard.RANGE,'--gateway','172.30.240.1','--opt',
            'com.docker.network.bridge.name='+guard.BRIDGE,'--label','linux-lab.isolation=v1',guard.NETWORK)
    config.write_text(json.dumps({'blocked_routes':sorted(set(routes))},indent=2)+'\n')
    shutil.copy2(ROOT/'host/network_guard.py','/usr/local/sbin/linux-lab-network-guard')
    Path('/etc/modules-load.d/linux-lab-network.conf').write_text('br_netfilter\n')
    Path('/etc/sysctl.d/90-linux-lab-network.conf').write_text('net.bridge.bridge-nf-call-iptables=1\nnet.bridge.bridge-nf-call-ip6tables=1\n')
    run('modprobe','br_netfilter')
    run('sysctl','-p','/etc/sysctl.d/90-linux-lab-network.conf')
    Path('/etc/systemd/system/'+SERVICE).write_text('''[Unit]
Description=Linux Lab student network admission guard
Requires=docker.service
After=docker.service
[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/local/sbin/linux-lab-network-guard
Restart=always
RestartSec=3
RuntimeDirectory=linux-lab-network
RuntimeDirectoryMode=0700
RuntimeDirectoryPreserve=yes
UMask=0077
[Install]
WantedBy=multi-user.target docker.service
''')
    fragment.write_text('''# Managed by linux-lab network installer
services:
  api:
    environment:
      DOCKER_NETWORK: linux-lab-students
      LAB_NETWORK_ISOLATION: required
    volumes:
      - /run/linux-lab-network:/run/linux-lab-network:ro
    networks:
      linux-lab-net: {}
      student-isolated:
        ipv4_address: 172.30.240.2
  proxy:
    networks:
      linux-lab-net: {}
      student-isolated:
        ipv4_address: 172.30.240.3
networks:
  student-isolated:
    external: true
    name: linux-lab-students
''')
    fragment.chmod(0o644)
    write_env(backend/'.env',{'COMPOSE_FILE':COMPOSE,'DOCKER_NETWORK':guard.NETWORK,'LAB_NETWORK_ISOLATION':'required'})
    run('systemctl','daemon-reload')
    run('systemctl','enable','--now',SERVICE)
    run('systemctl','restart',SERVICE)
    run('docker','compose','config','--quiet')
    run('docker','compose','up','-d','--force-recreate','api','proxy')
    # Readiness is verified by a real guard request from inside the API container.
    run('docker','compose','exec','-T','api','python','-c',
        'import time,network_guard\nfor attempt in range(20):\n try:\n  network_guard.container_options("linux-lab-students");print("Network admission guard healthy.");break\n except Exception:\n  if attempt==19: raise\n  time.sleep(1)')
    print('Installed: student isolation enabled. Test a new lab and follow docs/network-isolation.md.')


def rollback(backend):
    original=json.loads((STATE/'original.json').read_text())
    if original['backend']!=str(backend): raise RuntimeError('Backend directory mismatch.')
    idle(backend)
    run('docker','stop','linux-lab-api')
    idle(backend)
    write_env(backend/'.env',original['env'])
    run('docker','compose','up','-d','--force-recreate','api','proxy')
    # Only remove protection after the isolated network has no attached endpoints.
    n=json.loads(run('docker','network','inspect','linux-lab-students').stdout)[0]
    if n.get('Containers'): raise RuntimeError('Student network still has endpoints; protection retained.')
    run('systemctl','disable','--now',SERVICE)
    for tool,parent,target in [('iptables','DOCKER-USER','LL_STUDENTS'),('iptables','INPUT','DROP'),
                               ('ip6tables','FORWARD','LL_STUDENTS'),('ip6tables','INPUT','LL_STUDENTS')]:
        args=['-i','ll-students','-j',target]
        while run(tool,'-w','5','-C',parent,*args,check=False).returncode==0:
            run(tool,'-w','5','-D',parent,*args)
    for tool in ('iptables','ip6tables'):
        if run(tool,'-w','5','-S','LL_STUDENTS',check=False).returncode==0:
            run(tool,'-w','5','-F','LL_STUDENTS');run(tool,'-w','5','-X','LL_STUDENTS')
    run('docker','network','rm','linux-lab-students')
    (backend/'compose.network-isolation.yml').unlink(missing_ok=True)
    print('Rolled back to the previous network configuration. Saved homes were not changed.')
    print('Isolation is now OFF. Do not admit untrusted students until protection is restored.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['install','rollback'])
    parser.add_argument('backend',type=Path)
    args=parser.parse_args()
    if os.geteuid()!=0: parser.error('Run with sudo and pass the deployed backend directory.')
    os.umask(0o077)
    lock=open('/run/linux-lab-network-install.lock','a')
    fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
    backend=args.backend.resolve(strict=True)
    os.chdir(backend)
    try:
        (install if args.operation=='install' else rollback)(backend)
    except Exception as exc:
        raise SystemExit('FAILED: '+str(exc)+'\n'+(getattr(exc,'stderr','') or '')+'\nAdmission may remain stopped. Inspect the error; do not remove firewall rules while labs are attached.')
