# Single-host restart recovery

At API startup, after database initialization and before serving requests, the
API reconciles session records with Docker's managed-container inventory.

| Observed state | Startup behavior |
| --- | --- |
| Active/starting, within deadline, container running | Preserve session and original deadline; rebuild authenticated route |
| Container stopped or missing | End session as expired; remove stale route; release admission slot |
| Absolute/startup deadline passed | Remove container; expire record; remove route |
| Managed container without a DB record, or belonging to an ended session | Remove orphan container |
| Docker inventory unavailable or ownership/mapping invalid | Fail startup for operator investigation; do not infer that every desktop disappeared |

Cleanup uses `v=False` and never calls the volume deletion API. Persistent homes
and quota registry entries are retained. Temporary homes and unsaved process state
are not recoverable after container removal. The API does not automatically restart
stopped desktops. A new session is required following a host restart if Docker
stopped that desktop. Existing inactivity timestamps and absolute deadlines are
not reset by API restart; idle policy may therefore end an otherwise retained lab.

Only containers with the managed label, exact session-token label and expected
`linux-lab-session-<token>` name are eligible for recovery cleanup. Only generated
32-hex-token route filenames are removed. Other containers/configs are not touched.
This requires the existing single API worker; do not run multiple API instances
against the same Docker host/database. Recovery occurs at startup, not continuously
for every unexpected container exit. Runtime reconciliation and monitoring remain
follow-ups. API process restart interrupts in-flight requests; clients may need to
reconnect. Existing browser streams are not guaranteed uninterrupted.

## Deploy

End all labs and run the usual `scripts/install-classrooms.sh` deployment. No
student desktop rebuild or storage-service upgrade is required. Keep the verified
off-device backup. The installer refuses active sessions.

## Acceptance 1: API-only restart

1. Start a persistent lab, save `recovery-check.txt` in the home directory and note
   the remaining time. Perform the restart promptly so the idle deadline does not
   obscure the result.
2. On the Pi:

   ```bash
   cd ~/linux-lab/backend
   docker compose restart api
   docker compose logs --tail=60 api
   ```

3. Confirm the log contains `Session recovery: retained=1 ended=0 removed=0`
   for a single running lab. Reconnect/refresh the existing session if needed.
   Its deadline must not receive a fresh full session duration. Check the file.

## Acceptance 2: host reboot with a disposable test session

Use only your own test lab. Save all work first; this intentionally interrupts
that desktop. Do not run while other students are working or a backup is running.

1. With the persistent test lab still active, run `sudo reboot` on the Pi.
2. Reconnect via SSH and check:

   ```bash
   systemctl is-active linux-lab-storage.service
   findmnt /srv/linux-lab-storage/pool
   cd ~/linux-lab/backend
   docker compose logs --tail=60 api
   docker ps -a --filter label=linux-lab.managed=true
   ```

3. With the current no-restart student-container policy, expect the old session
   to expire and its stopped container to be removed. Start a new lab using the
   same student/classroom/template. Check `recovery-check.txt`, the storage banner
   and that capacity has been released. A deleted or temporary home is not expected
   to preserve files. Do not manually delete volumes to release a slot.

Local tests cover missing/stopped/expired/orphan containers, route cleanup,
deadline preservation, ownership guard, Docker failure and retryable cleanup.
Real API-restart and host-reboot acceptance are still required on the Pi.
