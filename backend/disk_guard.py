"""Admission watermarks, not a quota on existing container writes."""
import os
import shutil
from fastapi import HTTPException


def snapshot(database):
    checks = []
    for name, path in [('Desktop writable-layer filesystem', '/'),
                       ('Database filesystem space', os.path.dirname(database) or '.')]:
        try:
            usage = shutil.disk_usage(path)
            stats = os.statvfs(path)
            free = stats.f_bavail * stats.f_frsize
            percent = free / usage.total * 100
            gib = free / 1024**3
            inode_low = stats.f_files > 0 and stats.f_favail / stats.f_files < .01
            status = ('CRITICAL' if gib < 2 or percent < 5 or inode_low else
                      'WARNING' if gib < 5 or percent < 10 else 'OK')
            detail = f'{gib:.1f} GiB available ({percent:.1f}%).'
            if inode_low:
                detail += ' Fewer than 1% of file entries remain.'
            checks.append({'name': name, 'status': status, 'detail': detail})
        except (OSError, ValueError, ZeroDivisionError):
            checks.append({'name': name, 'status': 'UNAVAILABLE', 'detail': 'Cannot verify disk space.'})
    return checks


def require_space(database):
    if any(c['status'] in ('CRITICAL', 'UNAVAILABLE') for c in snapshot(database)):
        raise HTTPException(503, 'New labs are paused because host disk space is low or cannot be verified. Contact the administrator. Existing saved files are retained.')
