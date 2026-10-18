#!/usr/bin/env bash
# Run from the deployed backend directory after installing the storage update.
set -euo pipefail
docker compose exec -T api python - <<'PY'
import os, sqlite3
with sqlite3.connect(os.environ.get('SESSION_DB','/data/sessions.db')) as db:
    db.execute('BEGIN IMMEDIATE')
    if db.execute("SELECT COUNT(*) FROM sessions WHERE status IN ('starting','active')").fetchone()[0]:
        raise SystemExit('End all labs before changing the pilot configuration.')
    row = db.execute("SELECT image FROM lab_templates WHERE id='cse-candidate-v1'").fetchone()
    if not row or row[0] != 'linux-lab:cse-candidate':
        raise SystemExit('Expected cse-candidate-v1 with image linux-lab:cse-candidate. No changes made.')
    db.execute("UPDATE lab_templates SET cpu_millis=4000 WHERE id='cse-candidate-v1'")
    db.execute("UPDATE classrooms SET max_sessions=1 WHERE template_id='cse-candidate-v1'")
print('CSE template CPU: 4000 millicores; CSE classroom slots: 1.')
PY
python3 - <<'PY'
from pathlib import Path
from datetime import datetime
p=Path('.env')
s=p.read_text()
backup=p.with_name('.env.before-storage-'+datetime.now().strftime('%Y%m%d%H%M%S'))
backup.write_text(s); backup.chmod(0o600)
updates={'PERSISTENT_HOME_TEMPLATES':'cse-candidate-v1', 'MAX_SESSIONS':'1'}
lines=s.splitlines()
lines=[line for line in lines if not any(line.startswith(k+'=') for k in updates)]
lines.extend(k+'='+v for k,v in updates.items())
p.write_text('\n'.join(lines)+'\n')
print('Enabled CSE storage infrastructure; assign student persistence in /admin. Global pilot capacity: one lab. Saved .env backup.')
PY
docker compose up -d --force-recreate api
