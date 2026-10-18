# Disk watermarks and bounded Docker logs

New labs check available blocks and inodes before preparing a saved home or
creating a container. Admission fails with HTTP 503 if either the API root
filesystem or database filesystem has less than 2 GiB available, less than 5%
available, or fewer than 1% of file entries available. An unreadable check also
blocks admission. Warning thresholds are 5 GiB and 10%. Resume of an existing
lab and file deletion/cleanup are not blocked by this check. Nothing is deleted
automatically. Once space is restored, admissions resume without a restart.

On this Pi, Docker writable layers and the API root filesystem use the same
ext4 backing filesystem. The database bind mount is checked separately. This
assumption must be verified if moving Docker data to a different filesystem or
using a remote Docker daemon. Separate backup mounts and saved-home pool space
are not measured by this check; the quota service enforces home allowances.

New desktops use Docker json-file logs with max-size=10m and max-file=3.
The Compose template also supplies these limits for API and proxy. Existing
containers need recreation to adopt logging changes. The installer below adds
only logging fields to the existing base Compose file, preserves overrides,
backs up the base file and rejects conflicting effective logging configuration.
Old Docker log history is removed when those containers are recreated.

## Deployment on the existing Pi

End all labs, then run the classroom installer for the updated API and frontend.
After it completes, while there are still no student labs:

```bash
python3 scripts/install-log-rotation.py "$HOME/linux-lab/backend"
```

No sudo is needed if your account already runs Docker. Do not run simultaneous
installers. The logging installer briefly stops admissions and recreates API and
proxy. It does not reinstall network isolation, storage or change COMPOSE_FILE.
If recreation fails, inspect `docker compose ps` and logs in the backend folder;
the saved Compose backup permits restoring the previous configuration.

## Acceptance

- System Health shows both disk checks and refreshes every 60 seconds while its
  page is visible. No background notifications or external messages are sent.
- A new lab opens normally, saved files remain and storage usage is visible.
- Check a new desktop's logs using the command below (replace NAME with its name):

```bash
docker inspect --format '{{json .HostConfig.LogConfig}}' NAME
```

Expect json-file, max-size 10m and max-file 3. The installer verifies API/proxy
settings automatically. Unit tests simulate low space and inaccessible filesystems;
do not fill the real SD card to test admission failure.

These watermarks are **not a hard limit on a running desktop**. An existing lab
can still fill writable paths outside its saved home, and disk use can change
between checks. Hard writable-layer limits, host memory monitoring and off-host
alerts remain pending. Do not label the product fully protected against disk
exhaustion on the strength of these checks alone.
