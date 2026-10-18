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
mkdir -p /run/lab-nginx /var/log/nginx
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
            raise SystemExit('UID 1000 already belongs to another account; refusing to change it.')
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
    script.write_text(updated)
    subprocess.run(['bash', '-n', str(script)], check=True)
    print('Candidate prepared: UID 1000; runtime nginx and dashboard under /run.')


if __name__ == '__main__':
    main()
