# Disposable read-only desktop startup trial

This is a compatibility probe, not a production change. LinuxServer's read-only
operation documentation warns that PUID/PGID changes may not apply and startup
scripts may behave differently. Existing student homes require UID 1000; never
attach them to this probe or adopt read-only mode solely because HTTP responds.

Reference: https://docs.linuxserver.io/misc/read-only/

End any running lab to free the Pi's memory, then:

```bash
python3 scripts/test-readonly-desktop.py
```

The script uses the already-installed `linux-lab:cse-candidate` image by immutable
image ID. It does not pull/build images, change host filesystems, change firewall
rules, connect to a network, publish a port, or attach saved homes. It creates one
container with a read-only root and bounded tmpfs mounts for /config (512 MiB),
/run (64 MiB, executable), /tmp (128 MiB), /var/log (16 MiB),
/var/lib/nginx (32 MiB) and a 4 MiB write probe.
Shared memory is 256 MiB; total memory is capped at 1536 MiB with no additional
swap allowance. Logs are capped at 2 MiB. Unknown declared image volumes are
rejected rather than silently creating unbounded volumes.

It waits up to roughly two minutes for three consecutive checks of UID 1000,
nginx, Selkies, Xvfb, XFCE and localhost HTTP readiness, then reports the
actual abc user ID and process names, confirms EROFS on root writes and ENOSPC on
the disposable 4 MiB mount, and prints the last 100 startup log lines. Finally it
removes only its own container and temporary data. On interruption, ordinary
Python cleanup runs; SIGKILL/power failure cannot run cleanup, so identify the
unique `linux-lab-ro-probe-*` container and remove only that container manually.

NOT READY is useful diagnostic evidence: do not repeatedly rerun or change the
live template. Send the report to determine which image startup paths need
changes. Even PASS leaves GUI applications, UID 1000, persistence, boot variants,
other writable Docker-managed mounts and runtime resource behaviour unvalidated.
The network is deliberately offline, so internet-dependent initialization may
also fail. This trial cannot prove complete filesystem coverage or production
readiness. No portal install command is needed for this diagnostic.

## First Pi result and adapted candidate

The original candidate rejected root writes and enforced the 4 MiB mount, but
startup failed: abc was UID 911, init-nginx wrote /etc/nginx and copied the
selected dashboard into /usr/share/selkies/web. No desktop processes started.

A separate build recipe now fixes abc to UID 1000 at build time, saves nginx
configuration as an immutable seed, and redirects /etc/nginx to /run/lab-nginx.
The init-nginx script copies the seed into that bounded temporary filesystem.
Generated dashboard assets go to /run/lab-web; the original web path is a symlink.
The build validates expected script markers. The inspected base reserves UID 1000
for dockremap; the candidate relocates that image-local account to an unused UID
in 20000–20999 before assigning abc UID 1000. Unexpected conflicting accounts
are rejected. Embedded Docker remains disabled; this candidate is not intended
for Docker-in-Docker labs. Host user namespaces and host accounts are unchanged.
No student volume is mounted or ownership changed on the host.

```bash
bash scripts/build-readonly-cse.sh
python3 scripts/test-readonly-desktop.py --image linux-lab:cse-readonly-candidate
```

This uses the installed CSE image ID without package downloads; it does not
replace linux-lab:cse-candidate or register a template. Other startup paths may
still need adaptation. Send the new probe output before any portal deployment.
Do not increase /run indefinitely if assets exceed its 64 MiB limit; inspect the
assets and choose a documented bound. Production adoption still requires GUI,
UID, persistent-home and complete writable-path acceptance.


## Second Pi result: XFCE starts, nginx cache blocked

The adapted image built successfully as 1b910caae8bd. UID/GID 1000, XFCE and
Xvfb were observed; root EROFS and the 4 MiB ENOSPC checks passed. Nginx
repeatedly failed to create /var/lib/nginx/body, and the desktop could not write
/de-pid. This is still NOT READY, not acceptance of a working browser desktop.

The probe now gives /var/lib/nginx a separate bounded 32 MiB tmpfs. The image
maps /de-pid to /run/lab-desktop/de-pid, with that runtime directory owned by
1000:1000. Existing readers continue using the original path. No root filesystem
write access or additional capabilities are granted. A new build and probe use
the same two commands above. No API installer or template changes are required.

Startup also reported denied chmod/sed operations, an Openbox backup failure,
a Steam symlink failure and an X11 socket-directory warning. These remain to
review; fixing nginx alone does not establish GUI or security compatibility.


## Audio startup dependency

The supplied svc-selkies script waits for /defaults/pid before attempting audio
sink setup. The previous probe had no pulseaudio or selkies process. To allow
normal audio startup without making the root filesystem writable, the candidate
now copies /defaults into an immutable build-time seed and maps /defaults to
/run/lab-defaults. An early init-adduser prelude restores that seed, owned by
1000:1000, before downstream desktop startup. The build rejects an unexpected
startup script or a seed larger than 8 MiB. Defaults, audio runtime files, nginx
configuration and generated dashboard assets share the existing 64 MiB /run
limit; no unlimited writable mount is introduced.

The probe now also requires a pulseaudio process. It does not create a fake PID
file or skip audio readiness. This tests the likely audio-path blocker; the
actual PulseAudio runtime result still needs verification on the Pi. A passing
process check does not prove browser audio works. Existing chmod/sed/Openbox
warnings remain unresolved and production adoption is still pending.
