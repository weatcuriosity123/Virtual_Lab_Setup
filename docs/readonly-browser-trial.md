# Read-only candidate: browser acceptance trial

The offline startup probe passed on the Pi with image `sha256:27f87563069257f360af430f880224095638b59fd61f8260cb49d66f6a4ba4d8`. This establishes startup, UID, HTTP and bounded-write checks only. Browser and IDE acceptance remain necessary.

End classroom labs first. On the Pi run:

```sh
python3 scripts/trial-readonly-desktop.py
```

Keep that SSH terminal open. The helper prints temporary credentials after readiness passes. It creates a separate internal Docker bridge and a fresh 512 MiB tmpfs home, with the same bounded runtime mounts as the offline probe. It checks HTTPS on the temporary container IP, uses four CPU cores and 1536 MiB memory, and keeps no saved home. No internet access is intended in this trial. Existing classroom templates and firewall rules are not changed.

The additional bridge route may make the production network guard refuse new admissions while this trial runs. Do not bypass the guard or start classroom labs concurrently.

In a second Windows PowerShell window:

```powershell
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:13001:TRIAL_CONTAINER_IP:3001 YOUR_PI_USER@YOUR_PI_HOST
```

Use the container IP printed by the helper. Replace YOUR_PI_USER and YOUR_PI_HOST with your usual SSH username and address. Leave this tunnel open and visit `https://localhost:13001`. The trial uses a self-signed certificate: the expected warning is for this localhost test. Enter the generated student credentials. Do not reuse your Cloudflare or college password. Localhost publication is not a substitute for authentication, particularly with older Docker releases.

Check:

1. The desktop renders and keyboard/mouse input works.
2. Create and reopen a file in Documents; this tests writes within the temporary home, not persistence across sessions.
3. Open VS Code from its launcher and terminal. Record any sandbox error rather than granting new capabilities or disabling container security.
4. Run `cse-smoke`, compile a small program, and open Wireshark. Packet capture privileges are deliberately not added.
5. If a sample exists, play `/usr/share/sounds/alsa/Front_Center.wav` using `paplay` after enabling browser audio; otherwise report audio as untested.

Use Ctrl+C in the Pi trial terminal when done. Normal execution also cleans up after 20 minutes of browser testing. This is not a durable scheduler: SIGKILL, host failure or abrupt terminal loss can leave resources behind. The helper prints exact resource names at startup; manually remove only those resources if necessary:

```sh
docker rm -f -v <printed-trial-container>
docker network rm <printed-trial-network>
sudo python3 /usr/local/sbin/linux-lab-network-guard check
```

Close the Windows tunnel with Ctrl+C. Report GUI, VS Code, compilation and audio results. Passing this trial does not yet establish saved-home compatibility or production security acceptance, and does not promote the candidate to a classroom template.

## Updated tunnel and VS Code trial

The Pi's internal-network trial did not expose the requested host port. The helper now omits port publication, checks authenticated HTTPS directly from the host to the temporary container, and prints an SSH command with that container's current IP and destination port **3001**. The earlier localhost-to-localhost tunnel command above is superseded by the printed command. Windows still opens `https://localhost:13001`.

For the tested VS Code namespace profile:

```sh
python3 scripts/trial-readonly-desktop.py --vscode-sandbox
```

The reviewed profile is downloaded and hash-checked using the offline probe's implementation. VS Code launches automatically with its tested namespace settings, extensions and GPU disabled, and a separate temporary user-data directory. No `--no-sandbox` is used. The script requires a renderer before announcing readiness. This is a private functional trial, not a policy deployment. Profile namespace exceptions apply to the whole disposable container.

Test editing/saving/reopening a file, opening Terminal > New Terminal, and executing a small Python or C program there. Record responsiveness and errors. Existing desktop menu launchers are not patched yet; test the automatically opened window. This trial has no internet or persistent home. End it with Ctrl+C and check the network guard as above.

The preceding untraced Pi probe observed a renderer with UID 1000, NoNewPrivs=1, two seccomp filters and no effective capabilities. Namespace links were unreadable; namespace separation has not been fully inspected. Production promotion still requires review beyond renderer startup.
