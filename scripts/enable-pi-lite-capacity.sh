#!/usr/bin/env bash
# Install the matching API before running. No student sessions may be active.
set -euo pipefail
backend=${1:-$HOME/linux-lab/backend}
image_id=${2:-sha256:e22b9fef70f182be93b256c8ad49e28e6505a97333bf5bd49d84dad064af29c9}
cd "$backend"
test -f .env
if [ "$(docker image inspect "$image_id" --format '{{index .Config.Labels "lab.runtime.profile"}}')" != programming-lite-readonly-v1 ]; then
  echo 'Expected the reviewed lightweight image profile.' >&2; exit 1
fi
if [ -n "$(docker ps -q --filter label=linux-lab.managed=true)" ]; then
  echo 'End all student labs before changing host capacity.' >&2; exit 1
fi
# Fail before modifying anything if the matching API has not been installed.
docker compose exec -T api python -c 'import desktop_runtime; assert callable(desktop_runtime.admission_units)'
docker compose stop api
restart_api() { docker compose up -d api; }
trap restart_api EXIT
# API is stopped: no new admissions can race the DB/config update.
docker compose run --rm --no-deps -T -e "LITE_IMAGE_ID=$image_id" --entrypoint python api - <<'PY'
import os,sqlite3
from pathlib import Path
from datetime import datetime,timezone
import classrooms
path=Path(os.environ['SESSION_DB'])
with sqlite3.connect(path) as db:
    if db.execute("SELECT count(*) FROM sessions WHERE status IN ('active','starting')").fetchone()[0]:
        raise SystemExit('Active/starting session records remain. No configuration was changed.')
    folder=path.parent/'backups';folder.mkdir(exist_ok=True)
    backup=folder/('before-pi-lite-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'.db')
    with sqlite3.connect(backup) as copy: db.backup(copy)
    db.execute('BEGIN IMMEDIATE')
    existing=db.execute("SELECT image FROM lab_templates WHERE id='programming-lite-v1'").fetchone()
    if existing and existing[0]!=os.environ['LITE_IMAGE_ID']:
        raise SystemExit('programming-lite-v1 already points to another image. Review before replacing it.')
    db.execute('''INSERT INTO lab_templates(id,name,image,memory_mb,cpu_millis,shm_mb,home_mb,pids,enabled)
        VALUES ('programming-lite-v1','Programming Lite',?,768,1000,128,128,256,1)
        ON CONFLICT(id) DO UPDATE SET memory_mb=768,cpu_millis=1000,shm_mb=128,home_mb=128,pids=256,enabled=1''',
        (os.environ['LITE_IMAGE_ID'],))
    db.execute("UPDATE classrooms SET max_sessions=CASE WHEN template_id='programming-lite-v1' THEN 3 ELSE 1 END")
    db.commit()
    print('Database backup:',backup)
    print('Lite template registered. Existing other classrooms are capped at one.')
PY
python3 - <<'PY'
from pathlib import Path
from datetime import datetime,timezone
import os,shutil,tempfile
p=Path('.env')
backup=p.with_name('.env.before-pi-lite-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
shutil.copy2(p,backup)
settings={'MAX_SESSIONS':'3','LAB_CAPACITY_MODE':'pi-lite3'}
lines=[]
for line in p.read_text().splitlines():
    key=line.split('=',1)[0].strip()
    if key not in settings:lines.append(line)
lines.extend(k+'='+v for k,v in settings.items())
fd,name=tempfile.mkstemp(prefix='.env-pi-lite-',dir='.')
try:
    with os.fdopen(fd,'w') as out:out.write('\n'.join(lines)+'\n')
    os.chmod(name,p.stat().st_mode & 0o777)
    os.replace(name,p)
finally:
    if os.path.exists(name):os.unlink(name)
print('Environment backup:',backup)
PY
docker compose up -d api
trap - EXIT
docker compose exec -T api python - <<'PY'
import os
assert os.environ.get('MAX_SESSIONS')=='3'
assert os.environ.get('LAB_CAPACITY_MODE')=='pi-lite3'
print('PASS: configured for three bounded lightweight labs OR one other lab.')
PY
echo 'In /admin, create a Programming Lite classroom with 3 slots.'
echo 'If the test college has a plan, explicitly allow programming-lite-v1 and 3 seats.'
echo 'Heavy labs still require exclusive host access regardless of college/classroom seat settings.'
