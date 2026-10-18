#!/usr/bin/env bash
# Read-only prerequisite check. Run on the Docker host, not inside a lab.
set -euo pipefail
root_dir=$(docker info --format '{{.DockerRootDir}}')
source_device=$(findmnt -n -o SOURCE -T "$root_dir")
printf '\nStorage mount:\n'
findmnt -T "$root_dir" -o TARGET,SOURCE,FSTYPE,OPTIONS
printf '\nKernel:\n'
uname -r
printf '\nFilesystem features (read only):\n'
if [ "$(findmnt -n -o FSTYPE -T "$root_dir")" = ext4 ]; then
  sudo tune2fs -l "$source_device" | sed -n '/Filesystem features:/p;/Default mount options:/p;/quota inode:/p'
fi
printf '\nQuota tools:\n'
for tool in quota quotaon setquota repquota chattr lsattr; do
  command -v "$tool" || true
done
printf '\nKernel quota configuration, if exposed:\n'
if [ -r /proc/config.gz ]; then
  zcat /proc/config.gz | sed -n '/^CONFIG_QUOTA/p;/^CONFIG_QFMT/p;/^CONFIG_QUOTACTL/p'
elif [ -r "/boot/config-$(uname -r)" ]; then
  sed -n '/^CONFIG_QUOTA/p;/^CONFIG_QFMT/p;/^CONFIG_QUOTACTL/p' "/boot/config-$(uname -r)"
else
  printf 'Kernel configuration not exposed here; this does not mean quotas are unsupported.\n'
fi
