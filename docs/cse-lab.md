# CSE lab template plan — not yet built

The current image is a custom `linux-lab:1.0` desktop. Do not replace the working
classroom template before the new image passes desktop and practical tests.

## Proposed core toolkit

| Area | Tools / exercises |
|---|---|
| Linux | Bash, coreutils, find, grep, sed, awk, Vim/Nano, process and file exercises |
| Programming | GCC/G++, Make, CMake, GDB, Python with venv/pip, JDK, Maven |
| Development | VS Code, Git, GitHub CLI (`gh`), Node.js/npm, curl, jq |
| Databases | SQLite plus PostgreSQL/MySQL clients; isolated database services per exercise |
| Networking | iproute2, ping, traceroute, DNS tools, tcpdump, Wireshark/TShark |
| Data exercises | NumPy, pandas, Matplotlib in a prepared Python environment |

This is a proposed curated set; package installation and executable versions need
validation on the selected base image. GitHub is a hosted service: provide Git,
`gh` and browser access, not a shared GitHub login baked into an image. VS Code
extensions and upstream licenses must be checked before distributing a paid image.

Use a glibc-based Debian/Ubuntu desktop candidate for the full VS Code offering;
retain the existing Alpine image until the replacement is verified. Official
VS Code Linux packages support ARM64. Image and package versions must be recorded
for the pilot; a floating latest image alone is not a reproducible build.

## Networking exercises

Start with provided PCAP files for Wireshark/TShark. Installing capture utilities
does not automatically permit live capture by the student user. Live capture
requires a tested privilege model consistent with `no-new-privileges`, limited
to isolated exercise traffic. Do not add host networking, privileged mode or the
host Docker socket to student desktops. Host/other-college capture is outside scope.
Docker administration exercises need a separate isolation design, not the host socket.

## Android lab

Android Studio on Linux does not officially support ARM CPUs. The Raspberry Pi
cannot be the supported Android Studio host. Plan a separate x86-64 lab image and
host, with measured memory/CPU/storage needs. Google's current minimum is 8 GB RAM
for Studio alone and 16 GB with the emulator; these are vendor workstation
requirements, not an established per-student capacity result. Emulator acceleration
also needs suitable virtualization support, which must be checked on the actual host.

## Before building

Collect Pi model, RAM, disk space and current image architecture. Then build a
separate candidate image, run one lab, validate IDE launch and sample C/Python/Java
programs, Git operations, PCAP viewing, startup/idle behavior and desktop cleanup.
Only register it as a selectable template after these checks. Persistent student
work is a later milestone; currently students must export work before termination.

Sources:
- https://developer.android.com/studio/install
- https://code.visualstudio.com/docs/setup/linux
- https://docs.linuxserver.io/images/docker-webtop/
