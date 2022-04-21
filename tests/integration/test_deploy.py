from typing import List
import pytest
from pytest_operator.plugin import OpsTest
from juju.unit import Unit
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
    resources = {"snapshot": "snapshot.tar.gz"}
    await ops_test.model.deploy(charm, resources=resources)
    await ops_test.model.add_relation("easyrsa:client", "etcd:certificates")
    await ops_test.model.wait_for_idle(wait_for_active=True, timeout=60 * 60)


async def test_status(ops_test):
    assert ops_test.model.applications["etcd"].units[0].workload_status == "active"


async def _get_leader(units: List[Unit]) -> Unit:
    for unit in units:
        if await unit.is_leader_from_status():
            return unit


async def test_leader(ops_test: OpsTest):
    leader = await _get_leader(ops_test.model.applications["etcd"].units)
    assert leader is not None


async def test_leader_daemon_status(ops_test: OpsTest):
    leader = await _get_leader(ops_test.model.applications["etcd"].units)
    action = await leader.run("systemctl is-active snap.etcd.etcd")
    assert action.status == "completed"
    assert "inactive" not in action.results["Stdout"]
    assert "active" in action.results["Stdout"]


async def test_config_snapd_refresh(ops_test: OpsTest):
    leader = await _get_leader(ops_test.model.applications["etcd"].units)
    action = await leader.run("snap get core refresh.timer")
    assert len(action.results["Stdout"].strip()) == len("dayX")

    await ops_test.model.applications["etcd"].set_config({"snapd_refresh": "fri5"})
    action = await leader.run("snap get core refresh.timer")
    assert len(action.results["Stdout"].strip()) == len("fri5")


async def test_node_scale_up(ops_test: OpsTest):
    if not len(ops_test.model.applications["etcd"].units) > 1:
        await ops_test.model.applications["etcd"].add_unit(2)
        await ops_test.model.wait_for_idle(wait_for_active=True, timeout=60 * 60)

    unit: Unit
    for unit in ops_test.model.applications["etcd"].units:
        action = await unit.run("systemctl is-active snap.etcd.etcd")
        assert action.status == "completed"
        assert "inactive" not in action.results["Stdout"]
        assert "active" in action.results["Stdout"]


async def test_cluster_health(ops_test: OpsTest):
    for unit in ops_test.model.applications["etcd"].units:
        cmd = "{} ETCDCTL_API=2 /snap/bin/etcdctl cluster-health".format(
            " ".join(certs)
        )
        action = await unit.run(cmd)
        assert action.status == "completed"
        assert "unhealthy" not in action.results["Stdout"]
        assert "unavailable" not in action.results["Stdout"]


async def test_leader_knows_all_members(ops_test: OpsTest):
    leader = await _get_leader(ops_test.model.applications["etcd"].units)
    cmd = "{} ETCDCTL_API=2 /snap/bin/etcdctl member list".format(" ".join(certs))
    action = await leader.run(cmd)
    assert action.status == "completed"
    members = action.results["Stdout"].strip().split("\n")
    assert "etcd cluster is unavailable" not in members
    assert len(members) == len(ops_test.model.applications["etcd"].units)


async def test_node_scale_down(ops_test: OpsTest):
    leader = await _get_leader(ops_test.model.applications["etcd"].units)
    await leader.destroy()
    await ops_test.model.wait_for_idle(wait_for_active=True, timeout=60 * 60)


async def test_health_check(ops_test: OpsTest):
    action = await ops_test.model.applications["etcd"].units[0].run_action("health")
    await action.wait()
    assert action.status == "completed"
    assert "cluster is healthy" in action.results["output"]
