"""Fail-closed admission check for opt-in single-host network isolation."""
import json
import os
import socket
from fastapi import HTTPException


def container_options(network):
    mode=os.getenv('LAB_NETWORK_ISOLATION','off')
    if mode=='off':
        if network=='linux-lab-students':
            raise HTTPException(503,'Isolated network requires its admission guard.')
        return {}
    if mode!='required' or network!='linux-lab-students':
        raise HTTPException(503,'Lab network isolation configuration is invalid.')
    try:
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(30)
            client.connect('/run/linux-lab-network/guard.sock')
            client.sendall(b'health\n')
            with client.makefile('rb') as stream:
                result=json.loads(stream.readline(4096))
        if result.get('ok') is not True or result.get('network')!=network:
            raise ValueError('Isolation unavailable')
    except (OSError,ValueError) as exc:
        raise HTTPException(503,'Lab network protection unavailable. Contact the administrator.') from exc
    return {'cap_drop':['NET_RAW','NET_ADMIN'],
            'sysctls':{'net.ipv6.conf.all.disable_ipv6':'1'},
            'dns':['1.1.1.1','8.8.8.8']}
