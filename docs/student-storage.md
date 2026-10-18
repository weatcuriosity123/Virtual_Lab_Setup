# Persistent student homes: single-host pilot

Opt in with `PERSISTENT_HOME_TEMPLATES=cse-candidate-v1` in backend `.env`, then
recreate the API. Other templates continue using temporary RAM-backed homes.
Cloudflare verified identity, classroom enrollment and an active per-student storage
subscription are required. The template environment variable is an infrastructure
allowlist, not an entitlement for every enrolled student. Never enable
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
retains data. No automated deletion or retention schedule is implemented. A confirmed admin
action can permanently delete a selected unattached saved home (see below). Existing
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
3. Open `/admin` → **Student storage subscriptions**. Select the classroom, enter
   your enrolled email and select Persistent. Set an optional future expiry. Save.
   Start a lab. In its desktop terminal:
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

## Manual subscriptions

The admin dashboard assigns temporary/persistent storage to 1–500 enrolled emails
in a classroom, with optional timezone-aware expiry. College admins are restricted
to their own colleges. Batch changes are atomic and audited. Enrollment is separate
from storage: re-enrolling a student does not grant or renew a storage subscription.
Payment processing and automatic paid-plan synchronization are not implemented.

On upgrading from the template-wide persistence pilot, everyone defaults to temporary
until explicitly assigned Persistent in the dashboard. Existing named volumes remain
untouched and are reused when the same student/classroom/template is enabled again.
Disable/expiry applies on the next start, not mid-session. Temporary files created
while a subscription is inactive are not merged into the saved home. Renew the
subscription before starting if the student needs their existing saved work.

No disk-size selector is exposed yet, because persistent quotas are not enforced.
The original Linux template's 300 MiB tmpfs cap still applies to its temporary homes;
the CSE template currently uses its own home_mb value (512 MiB in the pilot).
A future subscription quota must be enforced by the filesystem, not a periodic size
scan. On the observed Pi the Docker root is ext4 on /dev/mmcblk0p2, mounted rw,noatime.
Run `bash scripts/inspect-storage-host.sh` on the host to inspect quota prerequisites.
It does not enable quotas, remount or edit the filesystem. Plan and back up before
any root-filesystem feature changes. File-manager capacity reporting must also be
validated: a project quota does not necessarily appear as a separate filesystem size.

## Permanent deletion from the dashboard

Use `/admin` → **Saved student homes** → **Delete permanently**. Each row identifies
the student, classroom, template and a home-ID suffix. Type `DELETE student@email`
exactly as prompted. This removes that specific home, not every home belonging to
that email. Other classrooms/templates and backups remain untouched. The subscription
is unchanged; a future persistent session creates a fresh home. Deleting data is not
a substitute for revoking enrollment or disabling a subscription.

The API checks college scope, server-derived ownership, volume metadata, and running
AND stopped container references. It serializes deletion with session creation and
uses Docker removal without force. Deletion request/success/failure are audited.
Only ordinary local Docker home volumes can be deleted by this implementation;
external, bind or block-backed volumes are refused because deleting their Docker
record alone does not erase the files. Unknown/orphan volumes not resolvable from
session history require host-operator investigation. Preserve session history until
a dedicated storage registry is implemented. This is logical deletion, not guaranteed
secure erasure from an SD card or removal from separately maintained backups.

## Ext4 hard-quota verification

The observed Pi kernel has quota support and quota tools installed, but its root
ext4 filesystem does not have the `quota` or `project` feature. Do not enable these
features blindly on the running root filesystem. A separate quota-enabled storage
pool is the intended next step; migration and API enforcement are not implemented yet.

First run `sudo bash scripts/test-storage-quota.sh` on the Pi. It creates a disposable
64 MiB file in /var/tmp, formats ONLY that file with quota/project features, mounts
it, assigns a 4 MiB project quota and attempts an 8 MiB write as UID 65534. Success
means the write fails with `Disk quota exceeded`. Cleanup unmounts and removes the
test image. If unmount fails, the script retains the test path for investigation.
It does not alter root filesystem features, fstab or existing student data.

This script has shell syntax validation only in development; the actual kernel test
must run on the Pi. Passing it proves unprivileged project quota enforcement, not
complete container isolation or production readiness. Do not advertise persistent
plan limits until migration, restart behavior and container-level enforcement pass.
