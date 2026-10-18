#!/usr/bin/env bash
# Single-host pilot: dedicated ext4 image and root-only storage service.
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then echo 'Run with sudo and pass the backend directory.' >&2; exit 1; fi
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
backend_dir=${1:?Pass the absolute deployed backend directory}
pool_gib=${2:-8}
[[ "$backend_dir" = /* && "$pool_gib" =~ ^[0-9]+$ ]] || exit 1
((pool_gib >= 2 && pool_gib <= 64)) || { echo 'Pool size must be 2–64 GiB.'; exit 1; }
cd "$backend_dir"
test -f docker-compose.yml && test -f .env
for tool in python3 docker mkfs.ext4 fallocate chattr setquota rsync findmnt blkid systemctl systemd-escape; do
  command -v "$tool" >/dev/null || { echo "Install missing prerequisite: $tool" >&2; exit 1; }
done
if [ -f docker-compose.override.yml ] && ! grep -q '^# Managed by linux-lab quota installer$' docker-compose.override.yml; then
  echo 'An existing custom Compose override needs merging before installation.' >&2; exit 1
fi
if grep -q '^COMPOSE_FILE=' .env; then echo 'Custom COMPOSE_FILE detected; use the documented manual merge before installation.' >&2; exit 1; fi
docker compose exec -T api python - <<'PY'
import sqlite3,os
from pathlib import Path
assert 'quota_rpc' in Path('/app/storage.py').read_text(), 'Install the quota API update first.'
with sqlite3.connect(os.environ.get('SESSION_DB','/data/sessions.db')) as db:
    assert not db.execute("SELECT COUNT(*) FROM sessions WHERE status IN ('active','starting')").fetchone()[0], 'End all labs first.'
PY
state=/var/lib/linux-lab-storage
pool=/srv/linux-lab-storage/pool
install -d -m 700 "$state" /srv/linux-lab-storage "$pool"
if [ ! -f "$state/pool.img" ]; then
  available=$(df --output=avail -B1 "$state" | tail -1)
  needed=$((pool_gib*1024*1024*1024))
  ((available >= needed+5*1024*1024*1024)) || { echo 'Not enough disk space: leave at least 5 GiB outside the pool.' >&2; exit 1; }
  # The exclusive creation prevents accidentally formatting an existing image.
  (set -o noclobber; : > "$state/pool.img")
  chmod 600 "$state/pool.img"
  fallocate -l "${pool_gib}G" "$state/pool.img"
  mkfs.ext4 -q -F -m 0 -O quota,project -E quotatype=prjquota "$state/pool.img"
  blkid -s UUID -o value "$state/pool.img" > "$state/pool.uuid"
elif [ ! -s "$state/pool.uuid" ]; then
  echo 'Existing image has no saved UUID. Inspect it; installer will not format it.' >&2; exit 1
fi
actual_uuid=$(blkid -s UUID -o value "$state/pool.img")
[ "$actual_uuid" = "$(cat "$state/pool.uuid")" ] || { echo 'Pool UUID mismatch.' >&2; exit 1; }
mount_unit=$(systemd-escape --path --suffix=mount "$pool")
cat > "/etc/systemd/system/$mount_unit" <<EOF
[Unit]
Description=Linux Lab persistent home quota pool
[Mount]
What=$state/pool.img
Where=$pool
Type=ext4
Options=loop,prjquota,nodev,nosuid
[Install]
WantedBy=multi-user.target
EOF
install -m 755 "$source_dir/host/storage_agent.py" /usr/local/sbin/linux-lab-storage-agent
cat > /etc/systemd/system/linux-lab-storage.service <<EOF
[Unit]
Description=Linux Lab quota storage agent
Requires=docker.service $mount_unit
After=docker.service $mount_unit
RequiresMountsFor=$pool
[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/local/sbin/linux-lab-storage-agent
Restart=on-failure
RestartSec=3
RuntimeDirectory=linux-lab-storage
RuntimeDirectoryMode=0700
UMask=0077
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now "$mount_unit"
systemctl enable linux-lab-storage.service
systemctl restart linux-lab-storage.service
python3 - <<'PY'
import socket,json,time
for i in range(15):
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(3);s.connect('/run/linux-lab-storage/agent.sock')
            s.sendall(b'{"op":"health"}\n')
            with s.makefile('rb') as f: response=json.loads(f.readline())
            assert response.get('ok'),response
        print('Storage service healthy.');break
    except Exception:
        if i==14: raise
        time.sleep(1)
PY
cat > docker-compose.override.yml <<'EOF'
# Managed by linux-lab quota installer
services:
  api:
    volumes:
      - /run/linux-lab-storage:/run/linux-lab-storage
EOF
python3 - <<'PY'
from pathlib import Path
from datetime import datetime
p=Path('.env');s=p.read_text()
b=p.with_name('.env.before-quota-'+datetime.now().strftime('%Y%m%d%H%M%S'))
b.write_text(s);b.chmod(0o600)
lines=[l for l in s.splitlines() if not l.startswith('PERSISTENT_STORAGE_BACKEND=')]
p.write_text('\n'.join(lines+['PERSISTENT_STORAGE_BACKEND=quota'])+'\n')
PY
docker compose up -d --force-recreate api
echo 'Quota backend enabled. Set student allowances in /admin; homes migrate on their next start.'
echo 'Original Docker homes remain as migration backups. Do not volume-prune them.'
