#!/usr/bin/env bash
set -euo pipefail
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -n "$(docker ps -q --filter label=linux-lab.managed=true)" ]; then
  printf 'End running labs before building this candidate.\n' >&2
  exit 1
fi
base_id="$(docker image inspect linux-lab:cse-candidate --format '{{.Id}}')"
printf 'Using installed CSE image: %s\n' "$base_id"
docker build --network none --build-arg "CSE_BASE=$base_id" \
  --label "lab.readonly.base=$base_id" \
  -t linux-lab:cse-readonly-candidate "$source_dir/student-image/cse-readonly"
printf '\nCandidate built. Classroom image and configuration unchanged.\n'
printf 'Next: python3 scripts/test-readonly-desktop.py --image linux-lab:cse-readonly-candidate\n'
