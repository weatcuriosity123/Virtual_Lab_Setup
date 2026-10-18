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
/run (64 MiB, executable), /tmp (128 MiB), /var/log (16 MiB) and a 4 MiB write probe.
Shared memory is 256 MiB; total memory is capped at 1536 MiB with no additional
swap allowance. Logs are capped at 2 MiB. Unknown declared image volumes are
rejected rather than silently creating unbounded volumes.

It waits roughly one to two minutes for localhost HTTP readiness, reports the
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
