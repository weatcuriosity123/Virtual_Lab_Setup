#!/usr/bin/env bash
set -euo pipefail
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# Compilation/downloads can contend with live students on a 4 GB Pi.
if [ -n "$(docker ps -q --filter label=linux-lab.managed=true)" ]; then
  printf 'End running labs before building the candidate image.\n' >&2
  exit 1
fi
base_tag='lscr.io/linuxserver/webtop:debian-xfce'
docker pull "$base_tag"
base_digest="$(docker image inspect "$base_tag" --format '{{index .RepoDigests 0}}')"
if [[ "$base_digest" != *@sha256:* ]]; then
  printf 'Could not resolve the base image digest.\n' >&2
  exit 1
fi
printf 'Building candidate from %s\n' "$base_digest"
docker build --build-arg "WEBTOP_BASE=$base_digest" \
  --label "lab.base.image=$base_digest" \
  -t linux-lab:cse-candidate "$source_dir/student-image/cse"
printf '\nCandidate built. Existing classroom images and configuration are unchanged.\n'
docker image inspect linux-lab:cse-candidate --format '{{.Os}}/{{.Architecture}} size={{.Size}} id={{.Id}}'
