#!/usr/bin/env python3
"""Apply the classroom background within the logged-in XFCE session."""
import re
import subprocess
import time
from pathlib import Path

IMAGE = '/usr/share/backgrounds/curiosity4u-wallpaper.png'


def run(*args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return None


def set_value(path, kind, value):
    args = ['xfconf-query', '-c', 'xfce4-desktop', '-p', path]
    existing = run(*args)
    if existing is None:
        return False
    if existing.returncode:
        args += ['--create', '--type', kind]
    result = run(*args, '--set', str(value))
    return result is not None and result.returncode == 0


def apply():
    result = run('xfconf-query', '-c', 'xfce4-desktop', '-l')
    if result is None or result.returncode:
        return False
    roots = set(re.findall(r'^(/backdrop/screen[^/]+/monitor[^/]+/workspace-?\d+)/',
                           result.stdout, re.MULTILINE))
    # New homes may not have any per-monitor properties yet.
    monitors = run('xrandr', '--query')
    count = run('xfconf-query', '-c', 'xfwm4', '-p', '/general/workspace_count')
    workspaces = 4
    if count is not None and count.returncode == 0 and count.stdout.strip().isdigit():
        workspaces = max(1, min(32, int(count.stdout.strip())))
    if monitors is not None and monitors.returncode == 0:
        for name in re.findall(r'^(\S+) connected', monitors.stdout, re.MULTILINE):
            for workspace in range(workspaces):
                roots.add(f'/backdrop/screen0/monitor{name}/workspace{workspace}')
    if not roots:
        return False
    success = True
    for root in sorted(roots):
        for prop, kind, value in [('last-image', 'string', IMAGE),
                                  ('image-style', 'int', 4),
                                  ('backdrop-cycle-enable', 'bool', 'false')]:
            success = set_value(f'{root}/{prop}', kind, value) and success
    return success


if __name__ == '__main__':
    if not Path(IMAGE).is_file():
        raise SystemExit('Classroom wallpaper is missing.')
    # Wait for XFCE's session bus and desktop initialization, with a bounded retry.
    for attempt in range(15):
        time.sleep(2)
        if apply():
            # Reapply once after startup defaults have settled.
            time.sleep(3)
            if apply():
                break
    else:
        raise SystemExit('Could not apply classroom wallpaper through XFCE.')
