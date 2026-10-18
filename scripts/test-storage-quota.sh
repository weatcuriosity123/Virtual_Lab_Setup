#!/usr/bin/env bash
# Isolated quota proof on a disposable 64 MiB image; never formats the root device.
set -euo pipefail
export LC_ALL=C
if [ "$(id -u)" -ne 0 ]; then
  echo 'Run with sudo on the Pi host.' >&2
  exit 1
fi
for tool in fallocate mkfs.ext4 mount umount mountpoint chattr setquota setpriv dd stat; do
  command -v "$tool" >/dev/null || { echo "Missing tool: $tool" >&2; exit 1; }
done
probe_dir=$(mktemp -d /var/tmp/linux-lab-quota-test.XXXXXXXX)
chmod 755 "$probe_dir"
cleanup() {
  if mountpoint -q "$probe_dir/mount"; then
    if ! umount "$probe_dir/mount"; then
      echo "Could not unmount $probe_dir/mount; kept test files for inspection." >&2
      return
    fi
  fi
  rm -rf -- "$probe_dir"
}
trap cleanup EXIT
mkdir "$probe_dir/mount"
fallocate -l 64M "$probe_dir/test.img"
mkfs.ext4 -q -F -m 0 -O quota,project -E quotatype=prjquota "$probe_dir/test.img"
mount -t ext4 -o loop,prjquota "$probe_dir/test.img" "$probe_dir/mount"
mkdir "$probe_dir/mount/student"
chattr -p 42001 +P "$probe_dir/mount/student"
chown 65534:65534 "$probe_dir/mount/student"
setquota -P 42001 0 4096 0 0 "$probe_dir/mount"
echo 'Trying an 8 MiB write with a 4 MiB project limit, as an unprivileged user...'
if setpriv --reuid=65534 --regid=65534 --clear-groups \
  dd if=/dev/zero of="$probe_dir/mount/student/test.bin" bs=1M count=8 status=none 2>"$probe_dir/result"; then
  echo 'FAIL: write exceeded the intended limit. Do not enable student quotas.' >&2
  exit 1
fi
cat "$probe_dir/result"
if ! grep -q 'Disk quota exceeded' "$probe_dir/result"; then
  echo 'FAIL: write failed for a reason other than quota enforcement.' >&2
  exit 1
fi
bytes=$(stat -c %s "$probe_dir/mount/student/test.bin")
if [ "$bytes" -gt 4194304 ]; then
  echo 'FAIL: resulting file exceeds 4 MiB.' >&2
  exit 1
fi
printf 'PASS: hard project quota enforced. File bytes written: %s\n' "$bytes"
echo 'The disposable image will now be unmounted and removed. Root filesystem features and student homes were not changed.'
