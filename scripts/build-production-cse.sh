#!/usr/bin/env bash
set -euo pipefail
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [ -n "$(docker ps -q --filter label=linux-lab.managed=true)" ]; then
  echo 'End classroom labs first.' >&2; exit 1
fi
base_id=$(docker image inspect linux-lab:cse-readonly-candidate --format '{{.Id}}')
docker build --network none --build-arg "CSE_BASE=$base_id" \
  --label "lab.production.base=$base_id" \
  -t linux-lab:cse-readonly-v1 "$source_dir/student-image/cse-production"
echo 'Release image built. Run install-classrooms.sh, then promote-cse-readonly.sh from this checkout.'
