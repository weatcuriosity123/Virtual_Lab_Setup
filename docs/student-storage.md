# Persistent student homes: single-host pilot

Opt in with `PERSISTENT_HOME_TEMPLATES=cse-candidate-v1` in backend `.env`, then
recreate the API. Other templates continue using temporary RAM-backed homes.
Cloudflare verified identity and classroom enrollment are required. Never enable
this for a public trial until storage quotas and backups are implemented.

A named Docker volume is mounted at `/config` (Webtop's user home). Files in
Documents/Desktop and editor settings inside that home survive manual termination,
idle termination and absolute expiry. Running processes, unsaved edits and packages
installed outside `/config` do not survive. Existing temporary sessions are NOT
migrated: export their work before ending them. Old VS Code flags are not changed.

The volume key hashes college, classroom, template, verified subject and email.
Different students/classrooms/templates get different volumes. Identity or template
ID changes require an explicit future migration; they do not automatically adopt
another home. Changing an image under the same template ID reuses that home; test
compatibility first. Home settings and any saved credentials also persist.

Membership checks still apply before mounting. Revocation blocks new access but
retains data. No automated deletion or retention schedule is implemented. Existing
volume labels are checked before reuse. A second container cannot attach the same
home through the API while any existing container references it, including stopped
orphan containers. Operators must investigate these rather than deleting data.
Run a single API process/replica: its creation lock is process-local.

## Deploy and validate

1. Export needed work and end all labs. Install via `scripts/install-classrooms.sh`.
2. From the deployed backend directory run the source checkout's
   `scripts/configure-cse-pilot.sh`. It requires the known CSE candidate template,
   sets CPU allowance to 4 cores, leaves RAM at its existing value, sets CSE class
   slots and GLOBAL capacity to one, and enables persistence for that template.
   The script backs up `.env` and recreates the API. It does not rebuild the student
   image. Four cores are a ceiling, not a performance guarantee or reserved CPUs.
3. Start a lab. In its desktop terminal:
   `printf 'storage acceptance\n' > "$HOME/Documents/persistence-test.txt"`
   (create Documents with `mkdir -p "$HOME/Documents"` if needed).
4. Manually end the lab. Start a NEW lab using the same account/classroom and read
   the file. Repeat with idle termination and 30-minute expiry.
5. Confirm the desktop authenticates with the NEW session credentials; old credentials
   must not grant access. Confirm a second enrolled account has no such file.
6. Verify the new container has NanoCPUs=4000000000 and a named mount at /config:
   `docker inspect --format '{{.HostConfig.NanoCpus}} {{json .Mounts}}' CONTAINER`

No live Docker volume or GUI acceptance tests were run in the development environment.
Mock tests verify scope isolation, mount reuse, identity gates and attachment guards.

## Pilot limitations and recovery

Named volumes survive session container removal, including the cleanup's `v=True`
(which removes anonymous volumes). Do NOT use volume-prune operations: unattached
student homes are still valuable. List homes using:
`docker volume ls --filter label=linux-lab.storage=home-v1`.

The old home_mb tmpfs size does NOT limit these disk volumes. They consume the
Docker host's storage and currently have no hard per-student quota. Monitor host
free space and `docker system df -v` during this one-student pilot. Persistence is
not a backup: SD card failure can still lose everything. Do not enable for a class
until hard quotas, offline volume backup/restore and retention controls are tested.
SQLite backups alone do not contain home files. Back up named volumes separately
while the relevant labs are stopped, preserving numeric UID/GID and permissions.

Disabling the opt-in restores temporary homes for new sessions and leaves named
volumes intact. Re-enabling with the same identity/classroom/template reattaches
saved data. Never delete a volume as part of deployment rollback.
