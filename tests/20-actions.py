#!/usr/bin/env python3

import os
import re
import unittest
import subprocess

import amulet


class TestActions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = amulet.Deployment(series='xenial')
        cls.d.add('etcd')
        cls.d.add('easyrsa', 'cs:~containers/easyrsa')
        cls.d.configure('etcd', {'channel': '3.0/stable'})
        cls.d.relate('easyrsa:client', 'etcd:certificates')
        cls.d.setup(timeout=1200)
        cls.d.sentry.wait_for_messages({'etcd':
                                        re.compile('Healthy*|Unhealthy*')})
        # cls.d.sentry.wait()
        cls.etcd = cls.d.sentry['etcd']

    def test_health_check(self):
        """
        Trigger health action
        """
        action_id = self.etcd[0].run_action('health')
        outcome = self.d.action_fetch(action_id,
                                      timeout=7200,
                                      raise_on_timeout=True,
                                      full_output=True)
        self.assertEqual(outcome['status'], 'completed')
        self.assertTrue("cluster is healthy" in outcome['results']['result-map']['message'])

    def test_snapshot_restore(self):
        """
        Trigger snapshot and restore actions
        """
        # Load dummy data
        self.load_data()
        self.assertTrue(self.is_data_present('v2'))
        self.assertTrue(self.is_data_present('v3'))

        filenames = {}
        for dataset in ['v2', 'v3']:
            # Take snapshot of data
            action_id = self.etcd[0].run_action('snapshot', {'keys-version': dataset})
            outcome = self.d.action_fetch(action_id,
                                          timeout=7200,
                                          raise_on_timeout=True,
                                          full_output=True)
            self.assertEqual(outcome['status'], 'completed')
            cpcmd = outcome['results']['copy']['cmd']
            subprocess.check_call(cpcmd.split())
            filenames[dataset] = os.path.basename(outcome['results']['snapshot']['path'])

        self.delete_data()
        self.assertFalse(self.is_data_present('v2'))
        self.assertFalse(self.is_data_present('v3'))

        # Restore v2 data
        cmd = 'juju attach etcd snapshot=%s' % filenames['v2']
        subprocess.check_call(cmd.split())
        action_id = self.etcd[0].run_action('restore')
        outcome = self.d.action_fetch(action_id,
                                      timeout=7200,
                                      raise_on_timeout=True,
                                      full_output=True)
        self.assertEqual(outcome['status'], 'completed')
        self.assertTrue(self.is_data_present('v2'))
        self.assertFalse(self.is_data_present('v3'))

        # Restore v3 data
        cmd = 'juju attach etcd snapshot=%s' % filenames['v3']
        subprocess.check_call(cmd.split())
        action_id = self.etcd[0].run_action('restore')
        outcome = self.d.action_fetch(action_id,
                                      timeout=7200,
                                      raise_on_timeout=True,
                                      full_output=True)
        self.assertEqual(outcome['status'], 'completed')
        self.assertFalse(self.is_data_present('v2'))
        self.assertTrue(self.is_data_present('v3'))

    def load_data(self):
        """
        Load dummy data

        """
        certs = "ETCDCTL_KEY_FILE=/var/snap/etcd/common/client.key " \
                "ETCDCTL_CERT_FILE=/var/snap/etcd/common/client.crt " \
                "ETCDCTL_CA_FILE=/var/snap/etcd/common/ca.crt " \
                "ETCDCTL_KEY=/var/snap/etcd/common/client.key " \
                "ETCDCTL_CERT=/var/snap/etcd/common/client.crt " \
                "ETCDCTL_CACERT=/var/snap/etcd/common/ca.crt"

        cmd = '{} ETCDCTL_API=2 /snap/bin/etcdctl set /etcd2key etcd2value'.format(certs)
        self.etcd[0].run(cmd)
        cmd = '{} ETCDCTL_API=3 /snap/bin/etcdctl --endpoints=http://localhost:4001 ' \
              'put etcd3key etcd3value'.format(certs)
        self.etcd[0].run(cmd)

    def is_data_present(self, version):
        '''
        Check if we have the data present on the datastore of the version
        Args:
            version: v2 or v3 etcd datastore

        Returns: True if the data is present

        '''
        certs = "ETCDCTL_KEY_FILE=/var/snap/etcd/common/client.key " \
                "ETCDCTL_CERT_FILE=/var/snap/etcd/common/client.crt " \
                "ETCDCTL_CA_FILE=/var/snap/etcd/common/ca.crt " \
                "ETCDCTL_KEY=/var/snap/etcd/common/client.key " \
                "ETCDCTL_CERT=/var/snap/etcd/common/client.crt " \
                "ETCDCTL_CACERT=/var/snap/etcd/common/ca.crt"

        if version == 'v2':
            cmd = '{} ETCDCTL_API=2 /snap/bin/etcdctl ls'.format(certs)
            data = self.etcd[0].run(cmd)
            return 'etcd2key' in data[0]
        elif version == 'v3':
            cmd = '{} ETCDCTL_API=3 /snap/bin/etcdctl --endpoints=http://localhost:4001 ' \
                  'get "" --prefix --keys-only'.format(certs)
            data = self.etcd[0].run(cmd)
            return 'etcd3key' in data[0]
        else:
            return False

    def delete_data(self):
        '''
        Delete all dummy data on etcd
        '''
        certs = "ETCDCTL_KEY_FILE=/var/snap/etcd/common/client.key " \
                "ETCDCTL_CERT_FILE=/var/snap/etcd/common/client.crt " \
                "ETCDCTL_CA_FILE=/var/snap/etcd/common/ca.crt " \
                "ETCDCTL_KEY=/var/snap/etcd/common/client.key " \
                "ETCDCTL_CERT=/var/snap/etcd/common/client.crt " \
                "ETCDCTL_CACERT=/var/snap/etcd/common/ca.crt"

        cmd = '{} ETCDCTL_API=2 /snap/bin/etcdctl rm /etcd2key'.format(certs)
        self.etcd[0].run(cmd)
        cmd = '{} ETCDCTL_API=3 /snap/bin/etcdctl --endpoints=http://localhost:4001 ' \
              'del etcd3key'.format(certs)
        self.etcd[0].run(cmd)


if __name__ == '__main__':
    unittest.main()
