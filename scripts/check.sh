#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m py_compile backend/main.py
python3 tests/test_lifecycle.py
python3 tests/test_classrooms.py
python3 tests/test_identity.py
js_file="$(mktemp --suffix=.js)"
trap 'rm -f "$js_file"' EXIT
python3 - "$js_file" <<'PY'
import re, sys
from pathlib import Path
source = Path('backend/frontend/index.html').read_text()
Path(sys.argv[1]).write_text('\n'.join(re.findall(r'<script>(.*?)</script>', source, re.S)))
PY
node --check "$js_file"
printf 'Python lifecycle and JavaScript syntax checks passed.\n'
