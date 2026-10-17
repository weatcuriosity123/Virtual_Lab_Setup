# Operations and security

## Existing Pi installation

The current working directory is `~/linux-lab/backend`. This repository places equivalent files under `backend/`. Publish source from a separate Git checkout; do not replace the live directory merely to update GitHub.

For a later deployment, drain active sessions, back up source and SQLite, copy reviewed code/config, preserve `.env`, `data/` and `nginx/sessions/`, then run:

```bash
cd ~/linux-lab/backend
docker compose up -d --build api
docker compose restart proxy
curl --fail http://127.0.0.1:8080/api/health
docker compose logs --tail=80 api
```

Nginx resolves the fixed API hostname at configuration load; restart it after recreating the API. This can interrupt desktop connections, so perform planned updates outside class.

## Consistent database backup

Run from the backend directory; this uses SQLite's online backup API and keeps the result private under the ignored data directory:

```bash
docker compose exec -T api python - <<'PYCODE'
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
backup = Path('/data/backups')
backup.mkdir(exist_ok=True)
name = backup / ('sessions-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '.db')
with sqlite3.connect('/data/sessions.db') as source, sqlite3.connect(name) as target:
    source.backup(target)
print(name)
PYCODE
```

Protect backups: the database contains plaintext desktop passwords and feedback. Restoring it does not recreate deleted containers or `/config` tmpfs contents. End sessions before restoring; startup reconciliation is not implemented.

## Diagnostics

```bash
docker compose ps
docker compose logs --tail=100 api proxy
docker ps --filter label=linux-lab.managed=true
docker stats --no-stream
sudo journalctl -u cloudflared -n 80 --no-pager
```

A 502 can indicate a starting/stopped desktop, missing container route, stale API upstream address or wrong tunnel origin. Check local health, API/proxy logs, then tunnel logs. For desktop logs, use the relevant container name from `docker ps`; redact credentials and session IDs before sharing.

Deleting a Compose stack does not automatically remove dynamically created student containers. Use the portal/API to end labs before shutting down the stack. Avoid broad Docker prune commands on a host with unrelated workloads.

## Current security boundaries

- This is a prototype for supervised/trusted classes. Containers share a kernel; arbitrary student commands are not isolated like separate hardened VMs.
- The API mounts the host Docker socket and runs with powerful host control. Never mount that socket into student desktops.
- Student containers share a bridge network and may reach other services. Per-session network isolation and control-plane filtering are required before hostile-user multi-tenancy.
- A shared class code can be redistributed. Rate limiting, identity-based quotas and an admin audit trail are not implemented.
- Desktop passwords are stored in SQLite and browser sessionStorage. Treat database backups and browser access as sensitive; add stronger credential/storage controls for broader use.
- The legacy DELETE /sessions/{token} endpoint accepts a class code in a query parameter. Prefer the portal's password-header terminate endpoint and avoid query-string credentials in logs.
- The browser reports activity; direct desktop URLs bypass that wrapper. This is user-experience monitoring, not a tamper-proof activity/audit system. The installer allowlist can also extend idle time; the absolute session deadline still applies.
- Keep `.env`, SSH keys, tunnel tokens, databases and generated session routes out of Git. `.gitignore` prevents new accidental additions; it does not erase already committed secrets.
- For public deployment, add suitable identity controls, admission throttling, network restrictions and host monitoring. LinuxServer's built-in authentication is not a hardened public application gateway.

The additive request_id database migration supports start retries. Keep one API process and one expiry/idle monitor. Dependency and image tags are currently unpinned; record tested versions/digests before reproducible release builds.
