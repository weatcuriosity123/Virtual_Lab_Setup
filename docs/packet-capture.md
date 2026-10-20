# Student packet capture

The lab toolbar's **Capture Traffic** button captures only the active session's
`eth0` namespace. The endpoint uses the existing session password and verified
owner checks. A template must include `/usr/bin/dumpcap`, Python 3 and writable
`/tmp`; unsupported templates receive an explanatory error.

The helper runs the session's immutable image with a fixed command, no host/home
mounts, read-only root, no-new-privileges and only NET_RAW. Desktop capabilities
remain unchanged. Capture stops after 10 seconds, 2,000 packets or approximately
256 kB, whichever comes first; packets are truncated to 256 bytes. Helpers have
128 MiB memory, 0.5 CPU and 32 tasks. At most two captures run at once, and only
one per session. This is a short diagnostic capture, not full-payload recording.

The file is written as UID/GID 1000 to `/tmp/capture-check.pcapng`. Open it in
Wireshark using File → Open. Each capture replaces this file; copy it into the
saved home if it must survive lab termination. Wireshark's native capture button
is not enabled. Helpers are removed on completion/failure, session termination,
and API startup. Dumpcap also has its own time limit if the API stops.

## Deploy and verify on the Pi

End running labs, install with
`bash scripts/install-classrooms.sh "$HOME/linux-lab/backend"`, and reload the
portal. No desktop rebuild or template-image update is needed for CSE.

1. Start CSE, click Capture Traffic, and open the resulting file in Wireshark.
2. Repeat; confirm the file is replaced. Save a copy to the home if needed.
3. Try another session's credentials and verify capture is refused.
4. End a lab during capture. Confirm no `linux-lab.capture=true` helper remains.
5. Check network-guard health after capture and verify normal desktop/VS Code use.
6. On templates without dumpcap/Python, confirm the clear unsupported-template error.

Automated tests mock Docker; live capture and network-guard compatibility still
require this Pi acceptance check. The installer records source and database backups.
