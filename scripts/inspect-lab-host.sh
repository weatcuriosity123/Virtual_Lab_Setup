#!/usr/bin/env bash
set -euo pipefail
printf '\nDevice model\n'
if [ -r /proc/device-tree/model ]; then tr -d '\000' < /proc/device-tree/model; printf '\n'; fi
uname -m
printf '\nMemory\n'
free -h
printf '\nStorage\n'
df -h / "$HOME"
printf '\nCurrent desktop image\n'
docker image inspect linux-lab:1.0 --format '{{.Os}}/{{.Architecture}} size={{.Size}} id={{.Id}}'
