#!/usr/bin/env bash
set -euo pipefail
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [ -n "$(docker ps -q --filter label=linux-lab.managed=true)" ]; then
  echo 'End running student labs before building on the Pi.' >&2; exit 1
fi
# Do not pull a changed upstream image over the base already present on the tested Pi.
base_ref=${1:-lscr.io/linuxserver/webtop:debian-xfce}
base_id=$(docker image inspect "$base_ref" --format '{{.Id}}')
wallpaper="$source_dir/student-image/cse-production/curiosity4u-wallpaper.png"
if [ ! -s "$wallpaper" ]; then
  echo "Existing wallpaper not found: $wallpaper" >&2; exit 1
fi
build_context=$(mktemp -d)
trap 'rm -rf -- "$build_context"' EXIT
cp "$source_dir/student-image/programming-lite/Dockerfile" "$source_dir/student-image/programming-lite/smoke.sh" "$build_context/"
cp "$source_dir/student-image/cse-readonly/prepare.py" "$build_context/"
cp "$wallpaper" "$build_context/curiosity4u-wallpaper.png"
cp "$source_dir/student-image/cse-production/curiosity4u-wallpaper.desktop" "$build_context/"
python3 - "$source_dir/student-image/cse-production/set-wallpaper.py" "$build_context/set-wallpaper.py" <<'PY'
from pathlib import Path
import sys
text=Path(sys.argv[1]).read_text()
text=text.replace("('image-style', 'int', 4)", "('image-style', 'int', 3)")
if "('image-style', 'int', 3)" not in text:
    raise SystemExit('Wallpaper setter changed; review fit before building.')
Path(sys.argv[2]).write_text(text)
PY
docker build --build-arg "WEBTOP_BASE=$base_id" --label "lab.base.image=$base_id" \
  -t linux-lab:programming-lite-candidate "$build_context"
docker image inspect linux-lab:programming-lite-candidate \
  --format 'Candidate: {{.Id}} | {{.Os}}/{{.Architecture}} | bytes={{.Size}}'
echo 'Candidate built. Templates, college plans and host capacity have not been changed.'
echo 'Install the matching API code before registering this new runtime profile.'
