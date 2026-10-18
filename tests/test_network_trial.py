"""Test temporary firewall scope and cleanup; actual packet behavior needs Pi."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location('trial', Path(__file__).resolve().parents[1]/'scripts/test-network-isolation.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class TrialTests(unittest.TestCase):
    def exercise(self, fail=False):
        calls=[]
        def run(*args, **kwargs):
            calls.append(args)
            if fail and args[:3] == ('docker','exec',m.NAMES[0]):
                raise subprocess.CalledProcessError(1,args,stderr='internet probe failed')
            return subprocess.CompletedProcess(args,0,stdout='',stderr='')
        sock=MagicMock()
        sock.getsockname.return_value=('172.30.250.1',34567)
        with patch.object(m,'preflight'), patch.object(m,'run',side_effect=run), patch.object(m,'tcp'), patch.object(m.socket,'socket',return_value=sock), patch.object(m.threading,'Thread'):
            if fail:
                with self.assertRaises(subprocess.CalledProcessError):
                    m.main()
            else:
                m.main()
        return calls

    def test_rules_scoped_and_cleanup_order(self):
        calls=self.exercise()
        hooks=[c for c in calls if c[0] in ('iptables','ip6tables') and '-I' in c]
        self.assertEqual(len(hooks),4)
        for hook in hooks:
            self.assertIn(m.BRIDGE,hook)
        self.assertFalse(any(c[0] in ('iptables','ip6tables') and '-P' in c for c in calls))
        remove=[i for i,c in enumerate(calls) if c[:3]==('docker','rm','-f')]
        unhook=[i for i,c in enumerate(calls) if c[0] in ('iptables','ip6tables') and '-D' in c]
        self.assertLess(max(remove), min(unhook))
        self.assertEqual(calls[-1],('docker','network','rm',m.NETWORK))

    def test_failed_internet_probe_still_cleans_up(self):
        calls=self.exercise(fail=True)
        self.assertEqual(calls[-1],('docker','network','rm',m.NETWORK))

    def test_probe_execution_error_is_not_reported_as_blocked(self):
        with patch.object(m,'run',return_value=subprocess.CompletedProcess([],1,'','Python failed')):
            with self.assertRaisesRegex(RuntimeError,'failed to execute'):
                m.tcp('test','172.30.250.2',3000,False)


if __name__=='__main__':
    unittest.main()
