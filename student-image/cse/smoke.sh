#!/bin/sh
set -eu
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT HUP INT TERM
cd "$work"
for tool in gcc g++ make cmake gdb python3 pip3 java javac mvn node npm git gh code sqlite3 psql mysql tcpdump wireshark tshark ip dig; do
    command -v "$tool" >/dev/null || { printf 'Missing tool: %s\n' "$tool" >&2; exit 1; }
done
printf '#include <stdio.h>\nint main(void){puts("C OK");return 0;}\n' > hello.c
gcc hello.c -o hello
./hello
printf '#include <iostream>\nint main(){std::cout << "C++ OK" << std::endl;}\n' > hello.cpp
g++ hello.cpp -o hello-cpp
./hello-cpp
printf 'class Hello { public static void main(String[] args) { System.out.println("Java OK"); } }\n' > Hello.java
javac Hello.java
java Hello
python3 -c 'import numpy, pandas, matplotlib; print("Python scientific imports OK")'
python3 -m venv test-venv
test-venv/bin/python -c 'print("Python venv OK")'
node -e 'console.log("Node.js OK")'
test "$(sqlite3 :memory: 'SELECT 2+2;')" = 4
git init -q repo
printf 'CSE command-line smoke checks passed. Desktop and IDE GUI validation is still required.\n'
