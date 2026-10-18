"""Opt-in, single-host persistent homes. Never delete a student's named volume."""
import hashlib
import json
import os

from docker.errors import NotFound
from fastapi import HTTPException


def home_name(context, actor):
    # Bind to verified subject AND email; changing identity requires explicit migration.
    scope = [context['college_id'], context['classroom_id'], context['template_id'],
             actor.subject, actor.email.lower()]
    digest = hashlib.sha256(json.dumps(scope, separators=(',', ':')).encode()).hexdigest()
    return 'linux-lab-home-v1-' + digest


def home_options(client, context, actor, auth_mode):
    enabled = {x.strip() for x in os.getenv('PERSISTENT_HOME_TEMPLATES', '').split(',') if x.strip()}
    if context['template_id'] not in enabled:
        return {'tmpfs': {'/config': f"rw,size={context['home_mb']}m,mode=1777"}}
    if auth_mode != 'cloudflare' or not actor or not all(
        context.get(key) for key in ('college_id', 'classroom_id', 'template_id')
    ):
        raise HTTPException(403, 'Persistent homes require verified classroom membership.')
    name = home_name(context, actor)
    # Include stopped/orphaned containers: never share an editor profile, even if DB cleanup failed.
    if client.containers.list(all=True, filters={'volume': name}):
        raise HTTPException(409, 'Your saved home is attached to another lab. Resume or end that lab first; contact an admin if it has ended.')
    labels = {'linux-lab.storage': 'home-v1', 'linux-lab.home': name,
              'linux-lab.college': context['college_id'],
              'linux-lab.classroom': context['classroom_id'],
              'linux-lab.template': context['template_id']}
    try:
        volume = client.volumes.get(name)
    except NotFound:
        volume = client.volumes.create(name=name, labels=labels)
    if any((volume.attrs.get('Labels') or {}).get(k) != v for k, v in labels.items()):
        raise HTTPException(409, 'Saved-home ownership metadata does not match. Contact an admin.')
    return {'volumes': {name: {'bind': '/config', 'mode': 'rw'}}}
