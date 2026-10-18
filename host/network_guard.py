#!/usr/bin/env python3
"""Single-host IPv4 lab firewall and read-only root Unix health endpoint."""
import json
import ipaddress
import os
from pathlib import Path
import shlex
import socketserver
import subprocess
import sys

NETWORK = 'linux-lab-students'
BRIDGE = 'll-students'
SUBNET = '172.30.240.0/24'
RANGE = '172.30.240.128/25'
CHAIN = 'LL_STUDENTS'
SOCKET = '/run/linux-lab-network/guard.sock'
BLOCKED = ['0.0.0.0/8','10.0.0.0/8','100.64.0.0/10','127.0.0.0/8',
           '169.254.0.0/16','172.16.0.0/12','192.168.0.0/16','198.18.0.0/15',
           '224.0.0.0/4','240.0.0.0/4']
TRUSTED = {'linux-lab-api':'172.30.240.2', 'linux-lab-proxy':'172.30.240.3'}
HOOKS = [('iptables','DOCKER-USER'),('iptables','INPUT'),('ip6tables','FORWARD'),('ip6tables','INPUT')]


def run(*args, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=True, timeout=15)


def rules(tool):
    if tool == 'ip6tables':
        return [['-j','DROP']]
    out = [['-m','conntrack','--ctstate','INVALID','-j','DROP']]
    for address in TRUSTED.values():
        out += [['-s',address+'/32','-d',RANGE,'-p','tcp','-m','tcp','--dport','3000','-j','RETURN'],
                ['-s',RANGE,'-d',address+'/32','-m','conntrack','--ctstate','ESTABLISHED','--ctdir','REPLY','-j','RETURN']]
    out += [['-d',net,'-j','REJECT','--reject-with','icmp-port-unreachable'] for net in BLOCKED]
    # Block additional operator-configured local/VPN/public LAN routes too.
    extra=json.loads(Path('/etc/linux-lab-network.json').read_text()).get('blocked_routes',[])
    out += [['-d',net,'-j','REJECT','--reject-with','icmp-port-unreachable'] for net in extra if net not in BLOCKED]
    return out + [['-j','RETURN']]


def hook(tool, parent):
    target = 'DROP' if tool=='iptables' and parent=='INPUT' else CHAIN
    return ['-i',BRIDGE,'-j',target]


def check_rules():
    configured = BLOCKED + json.loads(Path('/etc/linux-lab-network.json').read_text()).get('blocked_routes',[])
    for row in json.loads(run('ip','-j','-4','route','show','table','all').stdout):
        dest=row.get('dst','default')
        if dest=='default' or row.get('dev')==BRIDGE:
            continue
        network=ipaddress.ip_network(dest,strict=False)
        if not any(network.subnet_of(ipaddress.ip_network(net)) for net in configured):
            raise RuntimeError('Host routes changed; update isolation before admitting labs.')
    for key in ('net.bridge.bridge-nf-call-iptables','net.bridge.bridge-nf-call-ip6tables'):
        if run('sysctl','-n',key).stdout.strip() != '1':
            raise RuntimeError('Bridge filtering is unavailable.')
    for tool in ('iptables','ip6tables'):
        actual=[shlex.split(line) for line in run(tool,'-w','5','-S',CHAIN).stdout.splitlines()]
        expected=[['-N',CHAIN]] + [['-A',CHAIN]+r for r in rules(tool)]
        if actual != expected:
            raise RuntimeError('Isolation firewall rules do not match the installed policy.')
    for tool,parent in HOOKS:
        lines=[shlex.split(line) for line in run(tool,'-w','5','-S',parent).stdout.splitlines()]
        jumps=[line for line in lines if line[:1]==['-A']]
        if not jumps or jumps[0] != ['-A',parent]+hook(tool,parent):
            raise RuntimeError('Isolation firewall hook is missing or not first.')
    forward=run('iptables','-w','5','-S','FORWARD').stdout.splitlines()
    jumps=[shlex.split(line) for line in forward if line.startswith('-A ')]
    if not jumps or jumps[0] != ['-A','FORWARD','-j','DOCKER-USER']:
        raise RuntimeError('Docker forwarding no longer reaches the guard first.')


def check_network(require_control=True):
    n=json.loads(run('docker','network','inspect',NETWORK).stdout)[0]
    if (n['Driver']!='bridge' or n.get('EnableIPv6') or
            n.get('Options',{}).get('com.docker.network.bridge.name')!=BRIDGE or
            n.get('Labels',{}).get('linux-lab.isolation')!='v1' or
            n['IPAM']['Config'] != [{'Subnet':SUBNET,'IPRange':RANGE,'Gateway':'172.30.240.1'}]):
        raise RuntimeError('Student network configuration changed.')
    seen=set()
    for cid, endpoint in (n.get('Containers') or {}).items():
        name=endpoint['Name']; address=endpoint['IPv4Address'].split('/')[0]
        if name in TRUSTED:
            if address!=TRUSTED[name]:
                raise RuntimeError('Control endpoint address changed.')
            seen.add(name)
            continue
        c=json.loads(run('docker','inspect',cid).stdout)[0]
        cfg=c['HostConfig']; labels=c['Config'].get('Labels') or {}
        drops={x.upper().removeprefix('CAP_') for x in cfg.get('CapDrop') or []}
        if (labels.get('linux-lab.managed')!='true' or cfg.get('Privileged') or
                cfg.get('CapAdd') or 'no-new-privileges:true' not in (cfg.get('SecurityOpt') or []) or not {'NET_RAW','NET_ADMIN'}.issubset(drops) or
                cfg.get('Sysctls',{}).get('net.ipv6.conf.all.disable_ipv6')!='1' or
                set(c['NetworkSettings']['Networks'])!={NETWORK}):
            raise RuntimeError('Unprotected endpoint attached to student network.')
    if require_control and seen!=set(TRUSTED):
        raise RuntimeError('API/proxy student-network endpoints unavailable.')


def apply():
    check_network(False)
    # Re-applying exact rules is safe. Repairing/changing rules requires no labs.
    try:
        check_rules()
        return
    except (RuntimeError,subprocess.SubprocessError):
        pass
    if run('docker','ps','-aq','--filter','label=linux-lab.managed=true').stdout.strip():
        raise RuntimeError('End all labs before installing or repairing isolation rules.')
    for tool in ('iptables','ip6tables'):
        if run(tool,'-w','5','-S',CHAIN,check=False).returncode:
            run(tool,'-w','5','-N',CHAIN)
        run(tool,'-w','5','-F',CHAIN)
        for rule in rules(tool):
            run(tool,'-w','5','-A',CHAIN,*rule)
    for tool,parent in HOOKS:
        args=hook(tool,parent)
        while run(tool,'-w','5','-C',parent,*args,check=False).returncode==0:
            run(tool,'-w','5','-D',parent,*args)
        run(tool,'-w','5','-I',parent,'1',*args)
    check_rules()


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(5)
        try:
            if self.rfile.readline(128) != b'health\n':
                raise RuntimeError('Unsupported guard request.')
            check_rules()
            check_network()
            result={'ok':True,'network':NETWORK}
        except Exception as exc:
            print('Network admission denied:',repr(exc),flush=True)
            result={'ok':False}
        self.wfile.write(json.dumps(result).encode()+b'\n')


if __name__=='__main__':
    if os.geteuid()!=0:
        raise SystemExit('Run the guard as root.')
    if len(sys.argv)>1 and sys.argv[1]=='check':
        check_rules();check_network();print('Network guard healthy.');sys.exit(0)
    apply()
    os.umask(0o077)
    Path(SOCKET).parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    Path(SOCKET).unlink(missing_ok=True)
    with socketserver.UnixStreamServer(SOCKET,Handler) as server:
        print('Network rules installed; admission guard listening.',flush=True)
        server.serve_forever()
