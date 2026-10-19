# VS Code sandbox diagnostic (private, disposable)

The Pi host allowed unprivileged user namespaces. Docker 26.1.5's baseline profile rejected `unshare --user`; the same upstream profile plus an exact `unshare(CLONE_NEWUSER)` rule allowed it with no container capabilities and no-new-privileges retained. This isolates one blocker, not complete Electron sandbox compatibility.

End classroom and browser trials, then run:

```sh
python3 scripts/test-vscode-sandbox.py
```

No image rebuild is required. The script downloads the upstream Moby v26.1.5 profile over HTTPS and verifies its canonical JSON SHA-256 before adding constrained namespace exceptions. The installed Debian Docker build may differ from upstream; this is a diagnostic policy, not a replacement production default. Other Docker versions are refused.

The desktop runs offline with a fresh temporary home, read-only root, bounded tmpfs mounts, resource and log limits, no-new-privileges, and no added capabilities. No production policy is updated. It runs VS Code with `--disable-setuid-sandbox` to investigate the namespace sandbox route, never `--no-sandbox`. Disabling the SUID helper does not itself prove that another sandbox is active.

After 20 seconds it prints startup logs and surviving Code process information: UID, capabilities, namespaces, NoNewPrivs and seccomp filters. A missing renderer is a failed startup result. A surviving renderer alone is not acceptance either: evidence must be reviewed for actual sandbox layers, and GUI behavior must still be tested. Further namespace/clone restrictions may remain; do not broaden rules automatically or add SYS_ADMIN.

Normal exit and Ctrl+C remove the disposable container and profile. On a hard interruption, remove only the printed `linux-lab-code-probe-*` container. No saved homes are mounted. The probe needs host internet access only to download the reviewed profile; the test container has no network.

Source: https://github.com/moby/moby/blob/v26.1.5/profiles/seccomp/default.json

## Clone follow-up

The first Electron probe failed with “No usable sandbox” despite successful unshare. Chromium's `Credentials::CanCreateProcessInNewUserNS` first uses clone(NEWUSER | SIGCHLD), which the original test did not permit. The follow-up adds four exact clone flag combinations: NEWUSER with optional NEWPID/NEWNET, always SIGCHLD, only on arm64/amd64. It does not allow arbitrary clone flags, clone3, setns or mount, and adds no capabilities. This is a source-informed hypothesis, not proof that all remaining launch requirements are satisfied.

Sources:
- https://chromium.googlesource.com/chromium/src/+/lkgr/sandbox/linux/services/credentials.cc
- https://chromium.googlesource.com/chromium/src/+/6718b706ff100957d755554cec783840a8f1f05b/sandbox/linux/services/namespace_sandbox.cc

## Failed renderer fork: trace diagnostic

The exact clone exceptions allowed startup to progress, but the Pi then reported `Zygote could not fork` and no surviving renderer. GPU/broker processes had two seccomp filters; this does not establish renderer sandbox success.

Build a separate diagnostic image and run:

```sh
bash scripts/build-cse-debug.sh &&
python3 scripts/test-vscode-sandbox.py --trace
```

The build installs strace in a new `linux-lab:cse-readonly-debug` image derived from the local candidate's immutable ID. It needs internet for Debian packages. Neither existing image tag nor classroom configuration is replaced. The runtime remains offline and uses the same test seccomp policy, no-new-privileges and capabilities as the untraced probe.

Tracing runs as UID 1000 with a 15-second timeout, writes only to bounded temporary storage, and reports selected process/namespace calls and errors before cleanup. It does not add SYS_PTRACE. Ptrace restrictions or changes caused by tracing may prevent reproduction; any such result is diagnostic only. An eventual fix must be checked again without tracing.

## Trace-confirmed renderer fork

The Pi trace reproduced the renderer launch failure and recorded:

```
clone(..., flags=CLONE_NEWPID|SIGCHLD) = -1 EPERM
```

NEWUSER and combined USER/PID/NET clone calls succeeded earlier in the same trace. The next diagnostic profile adds only the exact `CLONE_NEWPID | SIGCHLD` value (0x20000011) on arm64/amd64. This exception is container-wide, not restricted to the renderer; it remains a private diagnostic policy. No additional capabilities, arbitrary clone arguments, clone3, mount or setns are enabled.

Run `python3 scripts/test-vscode-sandbox.py` without `--trace` to verify the candidate under normal execution. No rebuild is needed. Any renderer evidence still requires review and subsequent GUI acceptance.
