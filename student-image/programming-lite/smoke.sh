#!/usr/bin/env bash
set -euo pipefail
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
for command in python3 gcc g++ make nano xfce4-terminal xfconf-query xfdesktop xrandr; do
  command -v "$command" >/dev/null
done
for command in code wireshark tshark chromium firefox; do
  if command -v "$command" >/dev/null; then
    echo "Unexpected heavy application: $command" >&2; exit 1
  fi
done
python3 -c 'assert sum(range(101)) == 5050; print("PASS: Python")'
printf '%s\n' '#include <stdio.h>' 'int main(void) { puts("PASS: C"); return 0; }' > "$work/main.c"
gcc -Wall -Werror "$work/main.c" -o "$work/c-check"
"$work/c-check"
printf '%s\n' '#include <iostream>' 'int main() { std::cout << "PASS: C++" << std::endl; }' > "$work/main.cpp"
g++ -Wall -Werror "$work/main.cpp" -o "$work/cpp-check"
"$work/cpp-check"
python3 -m venv "$work/venv"
"$work/venv/bin/python" -c 'import sys; assert sys.prefix != sys.base_prefix'
echo 'PASS: Python venv and required desktop commands; runtime streaming still needs a live test.'
