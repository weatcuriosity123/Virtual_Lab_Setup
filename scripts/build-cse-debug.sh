#!/usr/bin/env bash
set -euo pipefail
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [ -n "$(docker ps -q --filter label=linux-lab.managed=true)" ]; then
  echo 'End classroom labs before building on the Pi.' >&2
  exit 1
fi
base_id=$(docker image inspect linux-lab:cse-readonly-candidate --format '{{.Id}}')
docker build --build-arg "CSE_BASE=$base_id" \
  --label "lab.debug.base=$base_id" \
  -t linux-lab:cse-readonly-debug "$source_dir/student-image/cse-debug"
echo 'Diagnostic image built. Classroom and candidate images unchanged.'
