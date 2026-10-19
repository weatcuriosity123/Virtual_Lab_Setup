# VS Code sandbox diagnostic (private, disposable)

The Pi host allowed unprivileged user namespaces. Docker 26.1.5's baseline profile rejected `unshare --user`; the same upstream profile plus an exact `unshare(CLONE_NEWUSER)` rule allowed it with no container capabilities and no-new-privileges retained. This isolates one blocker, not complete Electron sandbox compatibility.

End classroom and browser trials, then run:

```sh
python3 scripts/test-vscode-sandbox.py
```

No image rebuild is required. The script downloads the upstream Moby v26.1.5 profile over HTTPS and verifies its canonical JSON SHA-256 before adding just that one exception. The installed Debian Docker build may differ from upstream; this is a diagnostic policy, not a replacement production default. Other Docker versions are refused.

The desktop runs offline with a fresh temporary home, read-only root, bounded tmpfs mounts, resource and log limits, no-new-privileges, and no added capabilities. No production policy is updated. It runs VS Code with `--disable-setuid-sandbox` to investigate the namespace sandbox route, never `--no-sandbox`. Disabling the SUID helper does not itself prove that another sandbox is active.

After 20 seconds it prints startup logs and surviving Code process information: UID, capabilities, namespaces, NoNewPrivs and seccomp filters. A missing renderer is a failed startup result. A surviving renderer alone is not acceptance either: evidence must be reviewed for actual sandbox layers, and GUI behavior must still be tested. Further namespace/clone restrictions may remain; do not broaden rules automatically or add SYS_ADMIN.

Normal exit and Ctrl+C remove the disposable container and profile. On a hard interruption, remove only the printed `linux-lab-code-probe-*` container. No saved homes are mounted. The probe needs host internet access only to download the reviewed profile; the test container has no network.

Source: https://github.com/moby/moby/blob/v26.1.5/profiles/seccomp/default.json
