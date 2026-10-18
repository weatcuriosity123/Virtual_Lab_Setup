#!/usr/bin/env python3
"""Add bounded logs to an existing standard Compose file without changing overrides."""
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def run(*args):
    return subprocess.check_output(args, text=True)


def main():
    os.umask(0o077)
    os.chdir(Path(sys.argv[1]).expanduser().resolve())
    if run('docker','ps','-aq','--filter','label=linux-lab.managed=true').strip():
        raise SystemExit('End labs and wait for their containers to be removed before installing log rotation.')
    path=Path('docker-compose.yml')
    original=path.read_text()
    updated=original
    for service in ('api','proxy'):
        pattern=r'(?ms)^  '+service+r':\n(.*?)(?=^  [\w-]+:|^\S|\Z)'
        match=re.search(pattern,updated)
        if not match:
            raise SystemExit('Unrecognized Compose layout. No files changed.')
        if re.search(r'^    logging:',match.group(),re.M):
            continue
        addition='    logging:\n      driver: json-file\n      options:\n        max-size: "10m"\n        max-file: "3"\n'
        index=match.start()+len('  '+service+':\n')
        updated=updated[:index]+addition+updated[index:]
    backup=path.with_name('docker-compose.yml.before-logs-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.write_text(original)
    subprocess.run(['docker','compose','stop','api'],check=True)
    mode=path.stat().st_mode & 0o777
    try:
        path.write_text(updated)
        os.chmod(path,mode)
        config=json.loads(run('docker','compose','config','--format','json'))
        for service in ('api','proxy'):
            logs=config['services'][service].get('logging',{})
            if logs.get('driver')!='json-file' or any(str(logs.get('options',{}).get(k))!=v for k,v in [('max-size','10m'),('max-file','3')]):
                raise ValueError('Existing logging override conflicts with the expected limits.')
    except Exception:
        path.write_text(original)
        subprocess.run(['docker','compose','start','api'],check=True)
        raise
    # Recheck before recreating services. Installation is a maintenance-window operation.
    if run('docker','ps','-aq','--filter','label=linux-lab.managed=true').strip():
        path.write_text(original)
        subprocess.run(['docker','compose','start','api'],check=True)
        raise SystemExit('A lab started during installation. Configuration restored; retry while admissions are idle.')
    print('Compose backup:',backup,flush=True)
    subprocess.run(['docker','compose','up','-d','--force-recreate','api','proxy'],check=True)
    for name in ('linux-lab-api','linux-lab-proxy'):
        value=json.loads(run('docker','inspect','--format','{{json .HostConfig.LogConfig}}',name))
        assert value['Type']=='json-file' and value['Config'].get('max-size')=='10m' and value['Config'].get('max-file')=='3',name
    print('PASS: API and proxy log rotation enabled. New student labs inherit limits from the API.')


if __name__=='__main__':
    if len(sys.argv)!=2:
        raise SystemExit('Usage: python3 scripts/install-log-rotation.py BACKEND_DIRECTORY')
    main()
