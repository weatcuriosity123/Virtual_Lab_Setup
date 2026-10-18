#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m py_compile backend/main.py
python3 tests/test_lifecycle.py
python3 tests/test_classrooms.py
python3 tests/test_storage.py
python3 tests/test_quota_agent.py
python3 tests/test_identity.py
js_file="$(mktemp --suffix=.js)"
trap 'rm -f "$js_file"' EXIT
python3 - "$js_file" <<'PY'
import re, sys
from pathlib import Path
scripts = []
for page in Path('backend/frontend').glob('*.html'):
    scripts.append('(function(){\n' + '\n'.join(re.findall(r'<script>(.*?)</script>', page.read_text(), re.S)) + '\n})();')
Path(sys.argv[1]).write_text('\n'.join(scripts))
PY
node --check "$js_file"
node tests/test_logout.cjs
printf 'Python lifecycle and JavaScript syntax checks passed.\n'
