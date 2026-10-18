"""Policy admission and exact firewall-state checks; Docker/kernel calls mocked."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
import network_guard as api
spec=importlib.util.spec_from_file_location('host_guard',ROOT/'host/network_guard.py')
host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)


class GuardTests(unittest.TestCase):
    def test_admission_off_and_invalid(self):
        with patch.dict(os.environ,{'LAB_NETWORK_ISOLATION':'off'}):
            self.assertEqual(api.container_options('linux-lab-net'),{})
            with self.assertRaises(api.HTTPException): api.container_options(host.NETWORK)
        with patch.dict(os.environ,{'LAB_NETWORK_ISOLATION':'broken'}):
            with self.assertRaises(api.HTTPException): api.container_options(host.NETWORK)

    def test_admission_denies_outage_and_false_health(self):
        with patch.dict(os.environ,{'LAB_NETWORK_ISOLATION':'required'}):
            with patch.object(api.socket,'socket',side_effect=OSError('offline')):
                with self.assertRaises(api.HTTPException) as ctx: api.container_options(host.NETWORK)
                self.assertEqual(ctx.exception.status_code,503)
            sock=MagicMock()
            sock.__enter__.return_value.makefile.return_value.__enter__.return_value.readline.return_value=b'{"ok":false}\n'
            with patch.object(api.socket,'socket',return_value=sock):
                with self.assertRaises(api.HTTPException): api.container_options(host.NETWORK)

    def test_admission_sets_network_restrictions(self):
        sock=MagicMock()
        sock.__enter__.return_value.makefile.return_value.__enter__.return_value.readline.return_value=json.dumps({'ok':True,'network':host.NETWORK}).encode()
        with patch.dict(os.environ,{'LAB_NETWORK_ISOLATION':'required'}),patch.object(api.socket,'socket',return_value=sock):
            options=api.container_options(host.NETWORK)
        self.assertEqual(options['cap_drop'],['NET_RAW','NET_ADMIN'])
        self.assertEqual(options['dns'],['1.1.1.1','8.8.8.8'])
        self.assertEqual(options['sysctls']['net.ipv6.conf.all.disable_ipv6'],'1')

    def test_private_rules_allow_only_control_reply(self):
        with patch.object(Path,'read_text',return_value='{"blocked_routes":[]}'):
            rules=host.rules('iptables')
        private=next(i for i,r in enumerate(rules) if '172.16.0.0/12' in r)
        for rule in rules[:private]:
            if '--ctstate' in rule and 'ESTABLISHED' in rule:
                self.assertIn('--ctdir',rule);self.assertIn('REPLY',rule)
        self.assertEqual(host.rules('ip6tables'),[['-j','DROP']])

    def test_exact_firewall_and_hook_order(self):
        with patch.object(Path,'read_text',return_value='{"blocked_routes":[]}'):
            def run(*args,**kwargs):
                if args[0]=='ip': output='[]'
                elif args[0]=='sysctl': output='1\n'
                elif args[-1]==host.CHAIN:
                    output='-N '+host.CHAIN+'\n'+'\n'.join(' '.join(['-A',host.CHAIN]+r) for r in host.rules(args[0]))
                elif args[0]=='iptables' and args[-1]=='FORWARD': output='-P FORWARD DROP\n-A FORWARD -j DOCKER-USER'
                else: output='-A '+args[-1]+' '+' '.join(host.hook(args[0],args[-1]))
                return subprocess.CompletedProcess(args,0,output,'')
            with patch.object(host,'run',side_effect=run): host.check_rules()
            def missing(*args,**kwargs):
                if args[-1]=='DOCKER-USER': return subprocess.CompletedProcess(args,0,'-N DOCKER-USER\n-A DOCKER-USER -j RETURN','')
                return run(*args,**kwargs)
            with patch.object(host,'run',side_effect=missing):
                with self.assertRaisesRegex(RuntimeError,'hook'): host.check_rules()

    def test_endpoint_configuration_and_capabilities(self):
        network={'Driver':'bridge','EnableIPv6':False,'Options':{'com.docker.network.bridge.name':host.BRIDGE},
                 'Labels':{'linux-lab.isolation':'v1'},'IPAM':{'Config':[{'Subnet':host.SUBNET,'IPRange':host.RANGE,'Gateway':'172.30.240.1'}]},
                 'Containers':{'api':{'Name':'linux-lab-api','IPv4Address':'172.30.240.2/24'},
                               'proxy':{'Name':'linux-lab-proxy','IPv4Address':'172.30.240.3/24'},
                               'student':{'Name':'linux-lab-session-test','IPv4Address':'172.30.240.129/24'}}}
        container={'Config':{'Labels':{'linux-lab.managed':'true'}},
                   'HostConfig':{'Privileged':False,'CapDrop':['NET_RAW','NET_ADMIN'],
                                 'SecurityOpt':['no-new-privileges:true'],'Sysctls':{'net.ipv6.conf.all.disable_ipv6':'1'}},
                   'NetworkSettings':{'Networks':{host.NETWORK:{}}}}
        def run(*args,**kwargs):
            data=[network] if args[1]=='network' else [container]
            return subprocess.CompletedProcess(args,0,json.dumps(data),'')
        with patch.object(host,'run',side_effect=run):
            host.check_network()
            container['HostConfig']['CapDrop']=[]
            with self.assertRaisesRegex(RuntimeError,'Unprotected'):host.check_network()
            container['HostConfig']['CapDrop']=['NET_RAW','NET_ADMIN']
            network['Containers']['api']['IPv4Address']='172.30.240.4/24'
            with self.assertRaisesRegex(RuntimeError,'address'):host.check_network()

    def test_create_session_denied_before_storage_or_docker(self):
        import asyncio
        import docker
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'CLASS_ACCESS_CODE':'test-network-code','SESSION_DB':tmp+'/sessions.db','SESSION_CONFIG_DIR':tmp+'/routes','LAB_NETWORK_ISOLATION':'required'}):
            with patch.object(docker,'from_env',return_value=MagicMock()):
                import main
            main.init_db()
            with patch.object(main.network_guard,'container_options',side_effect=api.HTTPException(503,'guard down')),patch.object(main.storage,'home_options') as home:
                with self.assertRaises(api.HTTPException) as ctx:
                    asyncio.run(main.create_session(main.CreateSession(access_code='test-network-code')))
                self.assertEqual(ctx.exception.status_code,503)
                home.assert_not_called()
                main.docker_client.containers.run.assert_not_called()

    def test_refuses_firewall_repair_while_labs_exist(self):
        with patch.object(host,'check_network'),patch.object(host,'check_rules',side_effect=RuntimeError('missing')),patch.object(host,'run',return_value=subprocess.CompletedProcess([],0,'student-container','')) as run:
            with self.assertRaisesRegex(RuntimeError,'End all labs'):host.apply()
            self.assertEqual(run.call_count,1)


if __name__=='__main__':unittest.main()
