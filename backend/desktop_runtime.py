"""Image-declared desktop runtime, restricted to the reviewed single-host release."""
import hashlib
import json
import os
from pathlib import Path
from fastapi import HTTPException

PROFILE = 'cse-readonly-v1'
LITE_PROFILE = 'programming-lite-readonly-v1'
PROFILE_SHA256 = '8500a19ef4bb3de486aea6116debfc8f2c039f40c773a09b254176b3ea0ab78c'
RUNTIME_TMPFS = {
    '/run': 'rw,exec,size=64m,mode=755',
    '/tmp': 'rw,exec,size=128m,mode=1777',
    '/var/log': 'rw,size=16m,mode=755',
    '/var/lib/nginx': 'rw,size=32m,mode=755',
    '/defaults': 'rw,size=16m,mode=700,uid=1000,gid=1000',
}


def options(client, image, context):
    labels = image.attrs.get('Config', {}).get('Labels') or {}
    profile = labels.get('lab.runtime.profile')
    if not profile:
        return {'security_opt': ['no-new-privileges:true']}
    if profile not in (PROFILE, LITE_PROFILE):
        raise HTTPException(503, 'Unsupported desktop runtime profile.')
    if os.getenv('LAB_NETWORK_ISOLATION') != 'required':
        raise HTTPException(503, 'Read-only desktops require network isolation.')
    if not client.version()['Version'].startswith('26.1.5'):
        raise HTTPException(503, 'Desktop sandbox requires review for this Docker version.')
    minimum = (1536, 256, 512) if profile == PROFILE else (768, 128, 256)
    if any(context[key] < limit for key,limit in zip(('memory_mb','shm_mb','pids'), minimum)):
        raise HTTPException(503, 'Read-only desktop resources are below the profile minimum.')
    try:
        data = json.loads(Path(__file__).with_name('cse-seccomp.json').read_text())
        encoded = json.dumps(data, sort_keys=True, separators=(',', ':'))
        if hashlib.sha256(encoded.encode()).hexdigest() != PROFILE_SHA256:
            raise ValueError('Profile integrity mismatch')
    except (OSError, ValueError) as exc:
        raise HTTPException(503, 'Desktop sandbox profile is unavailable.') from exc
    return {'read_only': True, 'tmpfs': dict(RUNTIME_TMPFS),
            'memswap_limit': f"{context['memory_mb']}m",
            'security_opt': ['no-new-privileges:true', 'seccomp=' + encoded]}


def merge_home(runtime, home):
    """Preserve the existing subscription-selected /config mount exactly."""
    result = dict(runtime)
    if runtime.get('read_only') and home.get('volumes') and os.getenv('PERSISTENT_STORAGE_BACKEND') != 'quota':
        raise HTTPException(503, 'Read-only saved homes require the quota storage backend.')
    overlap = set(runtime.get('tmpfs', {})) & set(home.get('tmpfs', {}))
    if overlap:
        raise HTTPException(503, 'Desktop runtime mount conflict.')
    result.update(home)
    if runtime.get('tmpfs') or home.get('tmpfs'):
        result['tmpfs'] = {**runtime.get('tmpfs', {}), **home.get('tmpfs', {})}
    return result


def admission_units(db, image, context):
    """Single-worker Pi policy: three bounded lite labs OR one other desktop."""
    mode = os.getenv('LAB_CAPACITY_MODE','standard')
    if mode not in ('standard','pi-lite3'):
        raise HTTPException(503,'Unknown host capacity policy.')
    labels = image.attrs.get('Config',{}).get('Labels') or {}
    bounded_lite = labels.get('lab.runtime.profile') == LITE_PROFILE and all(
        context[key] <= limit for key,limit in (
            ('memory_mb',768),('cpu_millis',1000),('shm_mb',128),('home_mb',128),('pids',256)))
    units = 1 if bounded_lite else 3
    if mode == 'pi-lite3':
        occupied = db.execute("""SELECT COALESCE(SUM(COALESCE(capacity_units,3)),0)
            FROM sessions WHERE status IN ('active','starting')""").fetchone()[0]
        if occupied + units > 3:
            raise HTTPException(429,'This Pi supports three lightweight labs or one other lab. End existing labs before switching types.')
    return units
