#!/usr/bin/env bash
set -euo pipefail
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
target_dir="${1:-$HOME/linux-lab/backend}"
cd "$target_dir"
test -f main.py && test -f Dockerfile && test -f frontend/index.html && test -f docker-compose.yml
# Read only: refuse to interrupt students.
docker compose exec -T api python - <<'PY'
import sqlite3, os
with sqlite3.connect(os.environ.get('SESSION_DB','/data/sessions.db')) as db:
    count=db.execute("SELECT COUNT(*) FROM sessions WHERE status IN ('active','starting')").fetchone()[0]
if count:
    raise SystemExit(f'{count} sessions still active/starting. End them or wait for cleanup, then retry.')
PY
stamp="$(date +%Y%m%d-%H%M%S)"
backup_dir="$target_dir/classrooms-backup-$stamp"
mkdir -p "$backup_dir/frontend" "$backup_dir/nginx"
cp main.py Dockerfile "$backup_dir/"
cp frontend/*.html "$backup_dir/frontend/"
if [ -f admin.py ]; then cp admin.py "$backup_dir/"; fi
cp nginx/default.conf "$backup_dir/nginx/"
if [ -f identity.py ]; then cp identity.py "$backup_dir/"; fi
if [ -f classrooms.py ]; then cp classrooms.py "$backup_dir/"; fi
docker compose exec -T api python - <<'PY'
import sqlite3,os
from datetime import datetime,timezone
from pathlib import Path
src=Path(os.environ.get('SESSION_DB','/data/sessions.db'))
folder=src.parent/'backups';folder.mkdir(exist_ok=True)
dst=folder/('before-classrooms-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'.db')
with sqlite3.connect(src) as a,sqlite3.connect(dst) as b:
    a.backup(b)
print('Database backup:',dst)
PY
cp "$source_dir/backend/main.py" "$source_dir/backend/classrooms.py" "$source_dir/backend/identity.py" "$source_dir/backend/admin.py" "$source_dir/backend/Dockerfile" .
cp "$source_dir/backend/frontend/"*.html frontend/
cp "$source_dir/backend/nginx/default.conf" nginx/default.conf
printf 'Source backup: %s\n' "$backup_dir"
if ! docker compose up -d --build api; then
  printf 'Build/start failed. Restore source files from the printed backup and rebuild the API.\n' >&2
  exit 1
fi
docker compose restart proxy
docker compose exec -T proxy nginx -t
docker compose exec -T api python - <<'PY'
import time,urllib.request
for attempt in range(20):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2) as r:
            assert r.status==200
        print('API healthy. Follow docs/classrooms.md to create your college and classroom.')
        break
    except Exception:
        if attempt==19: raise
        time.sleep(1)
PY
