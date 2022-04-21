import pytest
from pytest_operator.plugin import OpsTest
import logging

log = logging.getLogger(__name__)

certs = [
    "ETCDCTL_KEY_FILE=/var/snap/etcd/common/client.key",
    "ETCDCTL_CERT_FILE=/var/snap/etcd/common/client.crt",
    "ETCDCTL_CA_FILE=/var/snap/etcd/common/ca.crt",
    "ETCDCTL_KEY=/var/snap/etcd/common/client.key",
    "ETCDCTL_CERT=/var/snap/etcd/common/client.crt",
    "ETCDCTL_CACERT=/var/snap/etcd/common/ca.crt",
]


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    charm = await ops_test.build_charm(".")
    await ops_test.model.deploy("cs:~containers/easyrsa-441")
    await ops_test.model.deploy("cs:~containers/etcd-655")
    await ops_test.model.add_relation("easyrsa:client", "etcd:certificates")
    await ops_test.model.wait_for_idle(wait_for_active=True, timeout=60 * 60)

    await ops_test.model.applications["etcd"].refresh(path=charm)
    await ops_test.model.wait_for_idle(wait_for_active=True, timeout=60 * 60)

    jcmd = "{} ETCDCTL_API=2 /snap/bin/etcd.etcdctl set juju rocks".format(
        " ".join(certs)
    )
    action = await ops_test.model.applications["etcd"].units[0].run(jcmd)
    assert action.status == "completed"

    nscmd = "{} ETCDCTL_API=2 /snap/bin/etcd.etcdctl set nested/data works".format(
        " ".join(certs)
    )
    action = await ops_test.model.applications["etcd"].units[0].run(nscmd)
    assert action.status == "completed"


async def test_snap_action(ops_test: OpsTest):
    action = (
        await ops_test.model.applications["etcd"].units[0].run_action("snap-upgrade")
    )
    await action.wait()
    assert action.status == "completed"
    await validate_running_snap_daemon(ops_test)
    await validate_etcd_fixture_data(ops_test)


async def test_snap_upgrade_to_three_oh(ops_test: OpsTest):
    await ops_test.model.applications["etcd"].set_config({"channel": "3.4/stable"})
    await ops_test.model.wait_for_idle(wait_for_active=True, timeout=60 * 60)
    await validate_running_snap_daemon(ops_test)
    await validate_etcd_fixture_data(ops_test)


async def validate_etcd_fixture_data(ops_test: OpsTest):
    jcmd = "{} ETCDCTL_API=2 /snap/bin/etcd.etcdctl get juju".format(" ".join(certs))
    action = await ops_test.model.applications["etcd"].units[0].run(jcmd)
    assert action.status == "completed"
    assert "rocks" in action.results["Stdout"]

    nscmd = "{} ETCDCTL_API=2 /snap/bin/etcd.etcdctl get nested/data".format(
        " ".join(certs)
    )
    action = await ops_test.model.applications["etcd"].units[0].run(nscmd)
    assert action.status == "completed"
    assert "works" in action.results["Stdout"]


async def validate_running_snap_daemon(ops_test: OpsTest):
    cmd = "systemctl is-active snap.etcd.etcd"
    action = await ops_test.model.applications["etcd"].units[0].run(cmd)
    assert action.status == "completed"
    assert "active" in action.results["Stdout"]
