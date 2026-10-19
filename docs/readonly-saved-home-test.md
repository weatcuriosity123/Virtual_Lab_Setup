# Read-only desktop: saved-home compatibility

Browser acceptance on the Pi: desktop access and the reported non-VS-Code checks passed. VS Code fails normal launch with a sandbox-helper error; it opened only with `--no-sandbox`. That remains a private-test exception, not production acceptance.

Run this offline test after ending classroom and browser trials:

```sh
sudo python3 scripts/test-readonly-saved-home.py \
  /var/backups/linux-lab/first-quota-backup
```

The directory must be an existing verified cold backup made by `storage-backup.py`, not a tar archive or the live storage directory. Checksums are reverified. If multiple ready homes exist, the helper lists names and requires `--home EXACT_NAME`. These names and backup contents are private; do not commit them.

The helper pauses the API during testing and restores it if previously running. Allow several minutes and keep the SSH terminal open. It needs 4 GiB free under `/var/tmp`, the locally built read-only candidate, rsync, quota and filesystem utilities already used for quota installation.

It mounts the backup image read-only, copies one home to a separate 2 GiB ext4 image with project quotas, and verifies copy checksums/metadata before starting a desktop. The copied home receives a 1 GiB test allowance and 100,000 inode hard limit; a copy that cannot fit fails rather than changing the original allowance. Original numeric ownership is retained, and UID 1000 ownership of the home root is required.

Two sequential offline containers use only this copy and bounded runtime tmpfs mounts. Both must reach desktop process/HTTP readiness. A file written as UID 1000 must survive container deletion and recreation. A separate 4 MiB project on the same disposable filesystem must reject an 8 MiB write with EDQUOT on each run. The home project quota report is printed. This tests the filesystem mechanism separately from the copied home's allowance; it does not fill the copied home to its 1 GiB limit.

Normal completion and Python exceptions clean up containers and mounted test disks. SIGTERM and Ctrl+C also enter cleanup; SIGKILL or host power loss cannot. Cleanup failures print the retained paths/container. Never recursively delete a still-mounted test directory. Test data is private (root-only parent directory) and should not be shared.

Afterward:

```sh
docker ps --filter name=linux-lab-api
sudo python3 /usr/local/sbin/linux-lab-network-guard check
systemctl is-active linux-lab-storage.service
```

Acceptance is limited to the selected backup's home. Later changes in live homes, portal usage banners, browser behavior with the copied profile, VS Code sandboxing, and classroom rollout remain separate checks. Production templates, live homes, quotas and backup contents are not updated by this test.
