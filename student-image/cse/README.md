# CSE programming lab — candidate

Includes C/C++, Python, Java, Node.js, VS Code, Git/GitHub CLI, build/debug tools,
SQLite, PostgreSQL/MySQL clients, tcpdump, Wireshark/TShark, and basic data packages.
No Android Studio, Android emulator, Docker daemon, or database servers are installed.

Run `cse-smoke` from the student terminal for offline command-line checks.
Open VS Code and Wireshark from the Applications menu separately. Do not add
`--no-sandbox`, privileged mode or host networking to work around startup errors;
report the exact error and evaluate compatibility with the existing isolation.

Python: create a local venv (`python3 -m venv ~/project/.venv`) for project packages.
System NumPy/pandas/Matplotlib are available in the system Python; use
`--system-site-packages` when a venv needs those preinstalled modules.

GitHub is a hosted service, accessed through Git, `gh` or the browser. Never
share tokens or bake accounts into the image. User credentials/files inside the
lab are temporary. Export work before End Lab; persistent storage is not ready.

Networking starts with offline PCAP analysis. Capture privileges are not granted
to the student. Database clients need instructor-provided exercise databases.

The base digest and installed package versions are recorded for validation.
APT repository packages are not snapshot-pinned, so rebuilding later may produce
new versions. Preserve the validated image by digest/archive for the pilot.
