"""Build-time adaptation for the inspected Debian CSE startup script."""
from pathlib import Path
import pwd
import shutil
import subprocess


def rewrite(source):
    if source.count('NGINX_CONFIG=/etc/nginx/sites-available/default') != 1:
        raise ValueError('Unexpected nginx startup: config marker changed')
    if source.count('/usr/share/selkies/web') < 4:
        raise ValueError('Unexpected nginx startup: dashboard paths changed')
    # Keep static source dashboards immutable; only their generated copy is writable.
    source = source.replace('/usr/share/selkies/web', '/run/lab-web')
    prelude = '''# Candidate runtime configuration lives in bounded /run tmpfs.
mkdir -p /run/lab-nginx /run/lab-desktop /var/log/nginx
chown 1000:1000 /run/lab-desktop
cp -a /opt/cse-readonly/nginx/. /run/lab-nginx/
'''
    return source.replace('# nginx Path', prelude + '\n# nginx Path', 1)


def main():
    script = Path('/etc/s6-overlay/s6-rc.d/init-nginx/run')
    original = script.read_text()
    if original.count('# nginx Path') != 1:
        raise SystemExit('Unexpected startup script; candidate build stopped.')
    updated = rewrite(original)
    abc = pwd.getpwnam('abc')
    if abc.pw_uid != 1000:
        try:
            conflict = pwd.getpwuid(1000)
        except KeyError:
            conflict = None
        if conflict:
            # Only relocate the exact image-local account observed in the Pi base.
            # Embedded Docker is disabled for classroom containers.
            if conflict.pw_name != 'dockremap' or conflict.pw_dir != '/home/dockremap':
                raise SystemExit('Unexpected UID 1000 owner; refusing to change it.')
            occupied = {entry.pw_uid for entry in pwd.getpwall()}
            replacement = next((uid for uid in range(20000, 21000) if uid not in occupied), None)
            if replacement is None:
                raise SystemExit('No free candidate UID for dockremap.')
            subprocess.run(['usermod', '-u', str(replacement), 'dockremap'], check=True)
            print(f'Relocated image-local dockremap to UID {replacement}.')
        subprocess.run(['usermod', '-u', '1000', 'abc'], check=True)
    if pwd.getpwnam('abc').pw_gid != 1000:
        raise SystemExit('Unexpected abc group; refusing to change it.')
    # These are image-owned paths; no student volume is attached during the build.
    subprocess.run(['chown', '-R', '1000:1000', '/app', '/defaults'], check=True)
    nginx = Path('/etc/nginx')
    seed = Path('/opt/cse-readonly/nginx')
    if nginx.is_symlink() or seed.exists():
        raise SystemExit('Image already adapted or layout changed.')
    shutil.copytree(nginx, seed, symlinks=True)
    shutil.rmtree(nginx)
    nginx.symlink_to('/run/lab-nginx', target_is_directory=True)
    web = Path('/usr/share/selkies/web')
    if web.exists() or web.is_symlink():
        raise SystemExit('Unexpected generated dashboard in base image.')
    web.symlink_to('/run/lab-web', target_is_directory=True)
    pid = Path('/de-pid')
    if pid.exists() or pid.is_symlink():
        raise SystemExit('Unexpected desktop PID file in base image.')
    pid.symlink_to('/run/lab-desktop/de-pid')
    script.write_text(updated)
    subprocess.run(['bash', '-n', str(script)], check=True)
    print('Candidate prepared: UID 1000; runtime nginx and dashboard under /run.')


if __name__ == '__main__':
    main()
