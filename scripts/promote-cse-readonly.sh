#!/usr/bin/env bash
set -euo pipefail
backend_dir=${1:-$HOME/linux-lab/backend}
operation=${2:-promote}
if [[ "$operation" != promote && "$operation" != rollback ]]; then
  echo 'Usage: promote-cse-readonly.sh BACKEND_DIR [promote|rollback]' >&2; exit 1
fi
cd "$backend_dir"
docker compose exec -T api python - "$operation" <<'PY'
import sys, sqlite3, os, json
from pathlib import Path
from datetime import datetime, timezone
import docker, desktop_runtime, network_guard, disk_guard
operation=sys.argv[1]
client=docker.from_env()
path=Path(os.getenv('SESSION_DB','/data/sessions.db'))
template='cse-candidate-v1'
if client.containers.list(all=True,filters={'label':'linux-lab.managed=true'}):
    raise SystemExit('End all labs and let normal cleanup remove stopped labs before promotion/rollback.')
with sqlite3.connect(path,timeout=30) as db:
    db.row_factory=sqlite3.Row
    db.execute('BEGIN IMMEDIATE')
    if db.execute("SELECT COUNT(*) FROM sessions WHERE status IN ('active','starting')").fetchone()[0]:
        raise SystemExit('Active/starting sessions remain. No template change made.')
    row=db.execute('SELECT * FROM lab_templates WHERE id=?',(template,)).fetchone()
    if row is None: raise SystemExit('Expected existing cse-candidate-v1 template; no change made.')
    db.execute('''CREATE TABLE IF NOT EXISTS desktop_promotions (
        id INTEGER PRIMARY KEY, template_id TEXT NOT NULL, old_image TEXT NOT NULL,
        new_image TEXT NOT NULL, created_at TEXT NOT NULL, rolled_back INTEGER NOT NULL DEFAULT 0)''')
    if operation=='promote':
        disk_guard.require_space(str(path))
        network_guard.container_options(os.environ.get('DOCKER_NETWORK','linux-lab-net'))
        image=client.images.get('linux-lab:cse-readonly-v1')
        if (image.attrs.get('Config',{}).get('Labels') or {}).get('lab.runtime.profile')!=desktop_runtime.PROFILE:
            raise SystemExit('Release image runtime label missing.')
        desktop_runtime.options(client,image,dict(row))
        if os.getenv('PERSISTENT_STORAGE_BACKEND')!='quota':
            raise SystemExit('Expected quota storage backend.')
        if row['image']==image.id:
            print('Release already selected; no change needed.'); raise SystemExit(0)
        # Retain the exact old image ID, so tag changes cannot alter rollback.
        old=client.images.get(row['image']).id
        db.execute('INSERT INTO desktop_promotions(template_id,old_image,new_image,created_at) VALUES (?,?,?,?)',
                   (template,old,image.id,datetime.now(timezone.utc).isoformat()))
        target=image.id
        action='desktop.promote'
    else:
        entry=db.execute('SELECT * FROM desktop_promotions WHERE template_id=? AND rolled_back=0 ORDER BY id DESC LIMIT 1',(template,)).fetchone()
        if not entry or row['image']!=entry['new_image']:
            raise SystemExit('No matching promotion to roll back; no change made.')
        client.images.get(entry['old_image'])
        target=entry['old_image']
        db.execute('UPDATE desktop_promotions SET rolled_back=1 WHERE id=?',(entry['id'],))
        action='desktop.rollback'
    db.execute('UPDATE lab_templates SET image=? WHERE id=?',(target,template))
    db.execute('INSERT INTO admin_events(occurred_at,actor_email,action,target,details) VALUES (?,?,?,?,?)',
        (datetime.now(timezone.utc).isoformat(),'local-operator',action,template,
         json.dumps({'old_image':row['image'],'new_image':target})))
    db.commit()
print('Template',template,'now uses',target)
print('Template ID, memberships, storage entitlements and saved-home keys preserved.')
print('Start one lab through the portal and verify files, storage banner, VS Code and termination.')
PY
