#!/usr/bin/env python3
"""Disposable offline read-only startup probe; never attaches saved homes."""
import argparse
import json
import secrets
import subprocess
import time


def run(*args, check=True, timeout=30):
    return subprocess.run(args, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, check=check, timeout=timeout)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',default='linux-lab:cse-candidate')
    args=parser.parse_args()
    if run('docker','ps','-q','--filter','label=linux-lab.managed=true').stdout.strip():
        raise SystemExit('End active labs first so this probe does not compete for Pi memory.')
    result=run('docker','image','inspect',args.image,check=False)
    if result.returncode:
        raise SystemExit('Candidate image is unavailable. Complete its build successfully before running this probe.')
    info=json.loads(result.stdout)[0]
    declared=set((info['Config'].get('Volumes') or {}).keys())
    if declared-{'/config'}:
        raise SystemExit('Unexpected image volume declarations; inspect before testing: '+str(sorted(declared)))
    name='linux-lab-ro-probe-'+secrets.token_hex(6)
    cid=None
    try:
        command=['docker','create','--name',name,'--network','none','--read-only',
                 '--memory','1536m','--memory-swap','1536m','--cpus','2','--pids-limit','512',
                 '--shm-size','256m','--cap-drop','NET_RAW','--cap-drop','NET_ADMIN',
                 '--security-opt','no-new-privileges:true','--sysctl','net.ipv6.conf.all.disable_ipv6=1',
                 '--log-driver','json-file','--log-opt','max-size=2m','--log-opt','max-file=1',
                 '--env','PUID=1000','--env','PGID=1000','--env','START_DOCKER=false','--env','TZ=Asia/Kolkata']
        for mount in ['/config:rw,size=512m,mode=1777', '/run:rw,exec,size=64m,mode=755',
                      '/tmp:rw,exec,size=128m,mode=1777', '/var/log:rw,size=16m,mode=755',
                      '/var/lib/nginx:rw,size=32m,mode=755', '/quota-probe:rw,size=4m,mode=1777']:
            command+=['--tmpfs',mount]
        command.append(info['Id'])
        cid=run(*command).stdout.strip()
        print('Image:',info['Id'],flush=True)
        print('Offline probe: no ports, no saved homes, bounded temporary mounts.',flush=True)
        run('docker','start',cid)
        ready=False
        deadline=time.monotonic()+120
        stable=0
        while time.monotonic()<deadline:
            state=json.loads(run('docker','inspect','--format','{{json .State}}',cid).stdout)
            if not state['Running']:
                print('Container exited. Exit code:',state['ExitCode'],'OOM:',state['OOMKilled'])
                break
            try:
                response=run('docker','exec',cid,'python3','-c',
                             "import urllib.request,pwd,subprocess; "
                             "assert pwd.getpwnam('abc').pw_uid==1000; "
                             "names=set(subprocess.check_output(['ps','-eo','comm'],text=True).split()); "
                             "assert {'nginx','selkies','pulseaudio','Xvfb','xfce4-session'}<=names, names; "
                             "o=urllib.request.build_opener(urllib.request.ProxyHandler({})); "
                             "assert o.open('http://127.0.0.1:3000/', timeout=1).status==200",check=False,timeout=5)
                stable=stable+1 if response.returncode==0 else 0
            except subprocess.TimeoutExpired:
                stable=0
            if stable>=3:
                ready=True
                break
            time.sleep(2)
        state=json.loads(run('docker','inspect','--format','{{json .State}}',cid).stdout)
        if state['Running']:
            print(run('docker','exec',cid,'sh','-c','id abc; ps -eo comm | sort -u; df -h /run /tmp /var/lib/nginx /config; ls -ld /defaults /defaults/pid /defaults/native /run/lab-defaults 2>/dev/null',check=False).stdout)
            probe=run('docker','exec',cid,'python3','-c', '''import errno,os
try:
    open('/usr/.linux-lab-ro-probe','w').close()
except OSError as e:
    assert e.errno==errno.EROFS, e
    print('PASS: root filesystem rejects writes (EROFS).')
else:
    raise SystemExit('FAIL: root filesystem accepted a write.')
try:
    with open('/quota-probe/test.bin','wb') as f:
        for _ in range(8): f.write(b'x'*1048576)
except OSError as e:
    assert e.errno==errno.ENOSPC,e
    print('PASS: disposable 4 MiB mount rejects excess writes (ENOSPC).')
else:
    raise SystemExit('FAIL: temporary mount exceeded its limit.')
finally:
    if os.path.exists('/quota-probe/test.bin'): os.unlink('/quota-probe/test.bin')
''',check=False)
            print(probe.stdout)
            if probe.returncode:
                raise SystemExit('Filesystem probe failed; do not deploy.')
        print('Startup log tail (test container only):')
        print(run('docker','logs','--tail','100',cid,check=False).stdout)
        if not ready:
            raise SystemExit('NOT READY: read-only startup needs image changes. Production was not changed.')
        print('PASS: UID 1000, nginx, Selkies, PulseAudio, Xvfb, XFCE and HTTP response passed three consecutive checks.')
        print('NOT YET ACCEPTED: browser, IDE, persistence and all writable paths still need validation.')
    finally:
        if cid:
            result=run('docker','rm','-f','-v',cid,check=False)
            if result.returncode:
                print('CLEANUP FAILED: remove only test container',name,'using docker rm -f -v',cid)
                raise SystemExit(1)
            print('Disposable probe and its temporary data removed. Live configuration unchanged.')


if __name__=='__main__':
    main()
