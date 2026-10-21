# Programming Lite candidate

Purpose: Python/C/C++ terminal exercises and eventual 2–3-session workflow testing on
our Pi. The candidate retains the existing browser desktop connection and stretched
wallpaper, but excludes VS Code, Wireshark and browsers inside the lab. It does not
provide live packet capture; use the CSE template for that exercise.

Build uses the local Webtop Debian XFCE base pinned to its inspected image ID. It
adds only basic compilers, Python/venv, Make, Nano and the terminal. It reuses the
fail-closed startup adaptation from the reviewed read-only image and the checked
seccomp profile. Changed upstream startup layouts abort the build for review.
System packages are installed from the configured apt repositories at build time;
retain the resulting immutable image ID for promotion. Removing an inherited package
does not remove bytes from the base layer. Measure actual size and RAM after build.

The separate programming-lite-readonly-v1 profile has initial minima of 768 MiB RAM,
128 MiB shared memory and 256 tasks, while the CSE minima remain unchanged. These are
candidate settings, not a proven three-student capacity. Per-lab CPU is set separately
when registering the template. The existing Docker version/network/quota gates apply.

## Stage 1: build only

End labs. In the Pi checkout, keep the existing untracked wallpaper file, then run:

```bash
bash scripts/build-programming-lite.sh
```

The script runs Python/C/C++ and venv build checks. It does not modify the database,
register templates, change plans, install the API, or change MAX_SESSIONS.

## Stage 2: supervised one-session acceptance

Install the matching API code using the existing installer while labs are stopped.
Register the image by immutable ID as a separate template, initially using 768 MiB
RAM, 1000 CPU millis, 128 MiB shm, 128 MiB temporary home and 256 tasks. Keep global
capacity one and use a separate test classroom/student. If its college has a plan,
explicitly approve the new template and use an allowed time window. Keep persistence
off for this initial performance test so home settings do not affect measurements.

Verify login, wallpaper, terminal launch and the following from a student terminal:

```bash
programming-lite-smoke
```

Then test save/download, reconnect, End Lab and cleanup. Measure container memory,
CPU, pids.events and memory.events while compiling. Build-time success does not prove
that streaming or unprivileged compilation works under runtime restrictions.

## Stage 3: two, then three students

Only after the one-session test passes, use a controlled lite-only testing window.
Temporarily block admissions to every heavier classroom before raising global and
classroom/college seat caps. Otherwise a higher MAX_SESSIONS would also admit heavy
CSE desktops and could exhaust the Pi. Existing heavy template resource allocations
remain unchanged. Test two students first, then three if measured headroom allows.
Restore the one-seat global limit before re-enabling heavy classrooms. Mixed-template
RAM/CPU-aware admission is not implemented by college seat plans and remains future
work. Do not advertise three concurrent full CSE desktops from a lite-only test.
