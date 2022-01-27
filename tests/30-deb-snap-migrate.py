#!/usr/bin/env python3

import amulet
import os
import re
import unittest
import yaml

from amulet.helpers import juju

TEST_TIMEOUT = 600


class TestDeployment(unittest.TestCase):
    bundle_file = os.path.join(os.path.dirname(__file__), "30-deb-bundle.yml")

    @classmethod
    def setUpClass(cls):
        cls.d = amulet.Deployment(series="xenial")

        # Deploy the scenario from the bundle
        with open(cls.bundle_file) as f:
            bun = f.read()
            bundle = yaml.safe_load(bun)
        cls.d.load(bundle)
        cls.d.setup(timeout=TEST_TIMEOUT)

        cls.etcd = cls.d.sentry["etcd"]
        # This is a hacky work-around to amulet not supporting charm upgrades.
        juju(["upgrade-charm", "etcd", "--path", os.getcwd()])
        # This is kind of a litmus test.
        cls.d.sentry.wait_for_messages({"etcd": re.compile("snap-upgrade")})

        # this is the legacy location of these TLS certs. As of rev-25 this is
        # no longer the case, and this is safe to leave as is for the remainder
        # of this tests lifecycle.
        certs = (
            "ETCDCTL_KEY_FILE=/etc/ssl/etcd/client.key "
            "ETCDCTL_CERT_FILE=/etc/ssl/etcd/client.crt "
            "ETCDCTL_CA_FILE=/etc/ssl/etcd/ca.crt"
        )

        # preseed the deployment with some data keys before releasing execution
        cls.etcd[0].run("{} etcdctl set juju rocks".format(certs))
        cls.etcd[0].run("{} etcdctl set nested/data works".format(certs))

    def test_snap_action(self):
        """When the charm is upgraded, a message should appear requesting the
        user to run a manual upgrade."""

        action_id = self.etcd[0].run_action("snap-upgrade")
        # This by default waits 600 seconds, incrase in slower clouds.
        out = self.d.get_action_output(action_id, full_output=True)
        # This will be failed if the upgrade didnt work
        assert "completed" in out["status"]
        # This will be missing if the operation bailed early
        assert "results" in out.keys()
        self.validate_running_snap_daemon()
        self.validate_etcd_fixture_data()

    def test_snap_upgrade_to_three_oh(self):
        """Default configured channel is 2.3/stable. Ensure we can jump to
        3.0"""
        self.d.configure("etcd", {"channel": "3.0/stable"})
        self.d.sentry.wait()
        self.validate_running_snap_daemon()
        self.validate_etcd_fixture_data()

    def validate_etcd_fixture_data(self):
        """Recall data set by set_etcd_fixture_data to ensure it persisted
        through the upgrade"""

        # The spacing here is semi-important as its a string of ENV exports
        # also, this is hard coding for the defaults. if the defaults in
        # layer.yaml change, this will need to change.
        certs = (
            "ETCDCTL_KEY_FILE=/var/snap/etcd/common/client.key "
            "ETCDCTL_CERT_FILE=/var/snap/etcd/common/client.crt "
            "ETCDCTL_CA_FILE=/var/snap/etcd/common/ca.crt"
        )

        jcmd = "{} /snap/bin/etcd.etcdctl get juju".format(certs)
        juju_key = self.etcd[0].run(jcmd)
        nscmd = "{} /snap/bin/etcd.etcdctl get nested/data".format(certs)
        nested_key = self.etcd[0].run(nscmd)

        assert "rocks" in juju_key[0]
        assert "works" in nested_key[0]

    def validate_running_snap_daemon(self):
        """Validate the snap based etcd daemon is running after an op"""
        daemon_status = self.etcd[0].run("systemctl is-active snap.etcd.etcd")
        assert "active" in daemon_status[0]


if __name__ == "__main__":
    unittest.main()
