#!/usr/bin/env python3

import amulet
import unittest
import re


class TestDeployment(unittest.TestCase):
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
        # find the leader
        for unit in cls.etcd:
            leader_result = unit.run('is-leader')
            if leader_result[0] == 'True':
                cls.leader = unit

    def test_snapshot_restore(self):
        """
        Trigger snapshot and restore actions
        """
        action_id = self.etcd[0].run_action('snapshot')
        outcome = self.d.action_fetch(action_id,
                                      timeout=7200,
                                      raise_on_timeout=True,
                                      full_output=True)
        self.assertEqual(outcome['status'], 'completed')
        action_id = self.etcd[0].run_action('restore')
        outcome = self.d.action_fetch(action_id,
                                      timeout=7200,
                                      raise_on_timeout=True,
                                      full_output=True)
        self.assertEqual(outcome['status'], 'completed')

    def test_leader_status(self):
        ''' Verify our leader is running the etcd daemon '''
        status = self.leader.run('systemctl is-active snap.etcd.etcd')
        self.assertFalse("inactive" in status[0])
        self.assertTrue("active" in status[0])

    def test_node_scale(self):
        ''' Scale beyond 1 node because etcd supports peering as a standalone
        application.'''
        # Ensure we aren't testing a single node
        if not len(self.etcd) > 1:
            self.d.add_unit('etcd', timeout=1200)
            self.d.sentry.wait()

        for unit in self.etcd:
            status = unit.run('systemctl is-active snap.etcd.etcd')
            self.assertFalse(status[1] == 1)
            self.assertFalse("inactive" in status[0])
            self.assertTrue("active" in status[0])

    def test_cluster_health(self):
        ''' Iterate all the units and verify we have a clean bill of health
        from etcd '''

        certs = "ETCDCTL_KEY_FILE=/var/snap/etcd/common/client.key " \
                "ETCDCTL_CERT_FILE=/var/snap/etcd/common/client.crt " \
                "ETCDCTL_CA_FILE=/var/snap/etcd/common/ca.crt"

        for unit in self.etcd:
            cmd = '{} /snap/bin/etcdctl cluster-health'.format(certs)
            health = unit.run(cmd)
            self.assertTrue('unhealthy' not in health)
            self.assertTrue('unavailable' not in health)

    def test_leader_knows_all_members(self):
        ''' Test we have the same number of units deployed and reporting in
        the etcd cluster as participating'''

        # The spacing here is semi-important as its a string of ENV exports
        # also, this is hard coding for the defaults. if the defaults in
        # layer.yaml change, this will need to change.
        certs = "ETCDCTL_KEY_FILE=/var/snap/etcd/common/client.key " \
                "ETCDCTL_CERT_FILE=/var/snap/etcd/common/client.crt " \
                "ETCDCTL_CA_FILE=/var/snap/etcd/common/ca.crt"

        # format the command, and execute on the leader
        cmd = '{} etcdctl member list'.format(certs)
        out = self.leader.run(cmd)[0]
        # turn the output into a list so we can iterate
        members = out.split('\n')
        for item in members:
            # this is responded when TLS is enabled and we don't have proper
            # Keys. This is kind of a "ssl works test" but of the worst
            # variety... assuming the full stack completed.
            self.assertTrue('etcd cluster is unavailable' not in members)
        self.assertTrue(len(members) == len(self.etcd))

    def test_node_scale_down_members(self):
        ''' Scale the cluster down and ensure the cluster state is still
        healthy '''
        # Remove the leader
        self.d.remove_unit(self.leader.info['unit_name'])
        self.d.sentry.wait()
        # re-use the cluster-health test to validate we are still healthy.
        self.test_cluster_health()


if __name__ == '__main__':
    unittest.main()
