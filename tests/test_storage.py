"""Storage ownership, opt-in and attachment guards without a Docker daemon."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from docker.errors import NotFound
from fastapi import HTTPException
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import storage

context = dict(college_id='college', classroom_id='class', template_id='cse', home_mb=512)
alice = SimpleNamespace(subject='alice', email='alice@example.com')
bob = SimpleNamespace(subject='bob', email='bob@example.com')
name = storage.home_name(context, alice)
assert name != storage.home_name(context, bob)
for key in ('college_id', 'classroom_id', 'template_id'):
    assert name != storage.home_name({**context, key: 'other'}, alice)
assert 'alice' not in name
client = MagicMock()
client.containers.list.return_value = []
client.volumes.get.side_effect = NotFound('missing')
client.volumes.create.side_effect = lambda **kw: SimpleNamespace(attrs={'Labels': kw['labels']})
with patch.dict(os.environ, {'PERSISTENT_HOME_TEMPLATES': ''}):
    assert 'tmpfs' in storage.home_options(client, context, alice, 'cloudflare')
client.volumes.get.assert_not_called()
with patch.dict(os.environ, {'PERSISTENT_HOME_TEMPLATES': 'cse'}), patch.object(storage, 'subscription_active', return_value=True), patch.object(storage.classrooms, 'connect', return_value=MagicMock()), patch.object(storage.plans,'get',return_value=None), patch.object(storage.plans,'reserve_storage'):
    for actor, mode in [(None, 'cloudflare'), (alice, 'off')]:
        try:
            storage.home_options(client, context, actor, mode)
            raise AssertionError('unverified storage allowed')
        except HTTPException as exc:
            assert exc.status_code == 403
    first = storage.home_options(client, context, alice, 'cloudflare')
    labels = client.volumes.create.call_args.kwargs['labels']
    client.volumes.get.side_effect = None
    client.volumes.get.return_value = SimpleNamespace(attrs={'Labels': labels})
    assert storage.home_options(client, context, alice, 'cloudflare') == first
    assert first == {'volumes': {name: {'bind': '/config', 'mode': 'rw'}}}
    client.volumes.create.assert_called_once()
    client.containers.list.return_value = [object()]
    try:
        storage.home_options(client, context, alice, 'cloudflare')
        raise AssertionError('concurrent mount allowed')
    except HTTPException as exc:
        assert exc.status_code == 409
    client.containers.list.return_value = []
    client.volumes.get.return_value = SimpleNamespace(attrs={'Labels': {}})
    try:
        storage.home_options(client, context, alice, 'cloudflare')
        raise AssertionError('foreign volume adopted')
    except HTTPException as exc:
        assert exc.status_code == 409
print('PASS: persistent home opt-in, identity/scope separation, reuse, concurrent mount and metadata guards')
