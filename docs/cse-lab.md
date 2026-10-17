# CSE lab template — candidate recipe, Pi validation pending

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

## Build on the Pi

From the repository root, with no running student labs:

```bash
bash scripts/build-cse-image.sh
```

This pulls the Debian XFCE base, resolves its digest, and builds a separate
`linux-lab:cse-candidate`. The build runs command-line smoke checks and records
package versions in `/opt/cse-lab/packages.tsv`. No API deployment or template
switch is performed. The original `linux-lab:1.0` remains available.

This recipe has not been built in the assistant environment (no Docker daemon).
Successful syntax review is not evidence of package download/build or GUI success.
Send the final build output before registering a classroom template.

## After the build succeeds

Register a candidate for a private, one-student test using the existing CLI:

```bash
cd ~/linux-lab/backend
docker compose exec api python classrooms.py template-add cse-candidate-v1 \
  --name "CSE Programming (candidate)" --image linux-lab:cse-candidate \
  --memory-mb 1536 --cpu-millis 1500 --shm-mb 256 --home-mb 512 --pids 512
```

These limits are an initial experiment, not a verified capacity specification.
The tmpfs home consumes memory within the container budget. Create a separate
one-slot test classroom and enroll only the test operator. Do not assign real
students yet or change `STUDENT_IMAGE` globally. Shared template choices become
visible to college admins once registered; coordinate the candidate test.

Verify: desktop readiness/authentication, `cse-smoke` as the student, VS Code
editing/terminal, Java compilation, Wireshark launch and offline PCAP opening,
GitHub CLI presence (no account needed), resume, inactivity warning, termination
and feedback. Observe `docker stats` on the Pi during these exercises. If upstream
Selkies behavior or sandboxing differs, resolve it before promotion; do not weaken
security flags to get a quick pass. Android tooling is a separate x86-64 milestone.
