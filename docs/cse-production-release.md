# Promote the tested CSE desktop on the Pi

This release keeps the existing `cse-candidate-v1` template ID. Saved homes,
classroom membership and storage entitlements therefore continue to use their
existing keys. The API resolves the production image to its immutable Docker
image ID when a student starts a session.

## Preconditions

- The CSE candidate image and its read-only desktop, browser, VS Code and copied
  saved-home trials have passed on this Pi.
- The quota storage service is installed and healthy. The API environment has
  `PERSISTENT_STORAGE_BACKEND=quota` and
  `LAB_NETWORK_ISOLATION=required`.
- The Docker Engine is version 26.1.5, matching the reviewed seccomp profile.
- There are no running or starting labs. Export or save any work that needs to
  be kept before draining the classroom.
- The API database and student storage have current backups.

Do not proceed if a precondition fails. The runtime and promotion scripts fail
closed when the storage, network, Docker-version or seccomp checks are missing.

## Build, install and promote

The wallpaper binary is supplied separately on the build host. Copy the approved
PNG to `student-image/cse-production/curiosity4u-wallpaper.png` before building.
The build refuses if that file is missing. This avoids sending a large binary
through the GitHub chat connector; the resulting Docker image still includes it.

Run these commands on the Pi from the repository checkout. The release build
uses the candidate image already tested on this host and does not need network
access. The installer backs up the current API source and database before
replacing API code.

```bash
cd "$HOME/linux-lab-classrooms-update"
git status --short
git pull --ff-only

# Verify storage and network admission before changing the API.
sudo systemctl is-active linux-lab-storage.service
sudo python3 /usr/local/sbin/linux-lab-network-guard check

# Build a separate production image from the tested candidate's immutable ID.
bash scripts/build-production-cse.sh

# Install the API runtime, launcher wiring and seccomp profile.
bash scripts/install-classrooms.sh "$HOME/linux-lab/backend"

# Switch the existing template to the production image ID.
bash scripts/promote-cse-readonly.sh "$HOME/linux-lab/backend" promote
```

Promotion refuses if managed lab containers remain or the database has active
or starting sessions. It verifies the image runtime label, required isolation,
quota backend, resource limits and seccomp profile before changing the
template. It records the previous image ID in the application database.

## Portal acceptance

The production image includes the Curiosity4u wallpaper. An XFCE autostart
entry applies it at every desktop login, including existing saved homes.
It changes only wallpaper properties, disables wallpaper cycling, and uses
scaled mode to keep the entire image visible (different aspect ratios may
show borders). Students can change the background during a session; the
classroom background is restored on the next desktop login.
After rebuilding and promoting, start a new lab to see the change; already
running containers do not receive image changes. Verify the wallpaper in
both a fresh home and an existing saved home and confirm it survives ending
and recreating the lab. Runtime visual verification must be performed on the Pi.

Before opening the classroom to students, use the portal to start one lab with
the existing test account and verify:

1. The desktop opens and VS Code starts from its normal application launcher.
2. The existing saved files are present. Create and save a marker file.
3. The storage banner reports the expected usage and hard limit.
4. End the lab, reconnect, and confirm the marker remains.
5. Terminate the lab and confirm cleanup completes.
6. Check API, storage and network guard health:

```bash
sudo systemctl is-active linux-lab-storage.service
sudo python3 /usr/local/sbin/linux-lab-network-guard check
docker ps --filter name=linux-lab-api
```

Do not admit students until these checks pass. The copied-home test is not a
substitute for checking the current live home through the portal.

## Roll back

If portal acceptance fails, end all labs and wait for their containers to be
removed. Then restore the exact previous image ID recorded by promotion:

```bash
bash scripts/promote-cse-readonly.sh "$HOME/linux-lab/backend" rollback
```

Rollback preserves the template ID and its storage keys. It does not undo files
written to persistent homes by sessions started after promotion. Keep the
production image and database backups until acceptance is complete.
