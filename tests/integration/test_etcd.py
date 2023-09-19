from typing import List
import pytest
from pytest_operator.plugin import OpsTest
from juju.unit import Unit
import logging
import os

log = logging.getLogger(__name__)

certs = [
    "ETCDCTL_KEY_FILE=/var/snap/etcd/common/client.key",
    "ETCDCTL_CERT_FILE=/var/snap/etcd/common/client.crt",
    "ETCDCTL_CA_FILE=/var/snap/etcd/common/ca.crt",
    "ETCDCTL_KEY=/var/snap/etcd/common/client.key",
    "ETCDCTL_CERT=/var/snap/etcd/common/client.crt",
    "ETCDCTL_CACERT=/var/snap/etcd/common/ca.crt",
]


async def _unit_run(unit: Unit, jcmd: str, check: bool = True):
    action = await unit.run(jcmd)
    action = await action.wait()
    if check:
        assert action.status == "completed", f"Failed to run '{jcmd}'"
    return action


@pytest.mark.abort_on_fail
async def test_build_and_deploy(series: str, ops_test: OpsTest):
    charm = await ops_test.build_charm(".")
    await ops_test.model.deploy("easyrsa", application_name="easyrsa", channel="edge")
    resources = {"snapshot": "snapshot.tar.gz"}
    await ops_test.model.deploy(charm, resources=resources, series=series)
    await ops_test.model.add_relation("easyrsa:client", "etcd:certificates")
    await ops_test.model.wait_for_idle(wait_for_active=True, timeout=60 * 60)

    jcmd = "{} ETCDCTL_API=2 /snap/bin/etcd.etcdctl set juju rocks".format(
        " ".join(certs)
    )
    await _unit_run(ops_test.model.applications["etcd"].units[0], jcmd)

    nscmd = "{} ETCDCTL_API=2 /snap/bin/etcd.etcdctl set nested/data works".format(
        " ".join(certs)
    )
    await _unit_run(ops_test.model.applications["etcd"].units[0], nscmd)


async def _get_leader(units: List[Unit]) -> Unit:
    for unit in units:
        if await unit.is_leader_from_status():
            return unit


async def test_leader_daemon_status(ops_test: OpsTest):
    leader = await _get_leader(ops_test.model.applications["etcd"].units)
    action = await _unit_run(leader, "systemctl is-active snap.etcd.etcd")
    assert "inactive" not in action.results["stdout"]
    assert "active" in action.results["stdout"]


async def test_config_snapd_refresh(ops_test: OpsTest):
    leader = await _get_leader(ops_test.model.applications["etcd"].units)
    action = await _unit_run(leader, "snap get core refresh.timer")
    assert len(action.results["stdout"].strip()) == len("dayX")

    await ops_test.model.applications["etcd"].set_config({"snapd_refresh": "fri5"})
    action = await _unit_run(leader, "snap get core refresh.timer")
    assert len(action.results["stdout"].strip()) == len("fri5")


async def test_node_scale_up(ops_test: OpsTest):
    if not len(ops_test.model.applications["etcd"].units) > 1:
        await ops_test.model.applications["etcd"].add_unit(1)
        await ops_test.model.wait_for_idle(wait_for_active=True, timeout=60 * 60)

    unit: Unit
    for unit in ops_test.model.applications["etcd"].units:
        action = await _unit_run(unit, "systemctl is-active snap.etcd.etcd")
        assert "inactive" not in action.results["stdout"]
        assert "active" in action.results["stdout"]


async def test_cluster_health(ops_test: OpsTest):
    for unit in ops_test.model.applications["etcd"].units:
        cmd = "{} ETCDCTL_API=2 /snap/bin/etcdctl cluster-health".format(
            " ".join(certs)
        )
        action = await _unit_run(unit, cmd)
        assert "unhealthy" not in action.results["stdout"]
        assert "unavailable" not in action.results["stdout"]


async def test_leader_knows_all_members(ops_test: OpsTest):
    leader = await _get_leader(ops_test.model.applications["etcd"].units)
    cmd = "{} ETCDCTL_API=2 /snap/bin/etcdctl member list".format(" ".join(certs))
    action = await _unit_run(leader, cmd)
    members = action.results["stdout"].strip().split("\n")
    assert "etcd cluster is unavailable" not in members
    assert len(members) == len(ops_test.model.applications["etcd"].units)


async def test_node_scale_down(ops_test: OpsTest):
    if len(ops_test.model.applications["etcd"].units) == 1:
        return
    leader = await _get_leader(ops_test.model.applications["etcd"].units)
    await ops_test.model.destroy_unit(leader.name)
    await ops_test.model.wait_for_idle(wait_for_active=True, timeout=60 * 60)


async def test_health_check(ops_test: OpsTest):
    action = await ops_test.model.applications["etcd"].units[0].run_action("health")
    await action.wait()
    assert "cluster is healthy" in action.results["output"]


async def test_snap_action(ops_test: OpsTest):
    action = (
        await ops_test.model.applications["etcd"].units[0].run_action("snap-upgrade")
    )
    await action.wait()
    await validate_running_snap_daemon(ops_test)
    await validate_etcd_fixture_data(ops_test)


async def test_snap_upgrade_to_three_oh(ops_test: OpsTest):
    await ops_test.model.applications["etcd"].set_config({"channel": "3.4/stable"})
    await ops_test.model.wait_for_idle(wait_for_active=True, timeout=60 * 60)
    await validate_running_snap_daemon(ops_test)
    await validate_etcd_fixture_data(ops_test)


async def validate_etcd_fixture_data(ops_test: OpsTest):
    jcmd = "{} ETCDCTL_API=2 /snap/bin/etcd.etcdctl get juju".format(" ".join(certs))
    action = await _unit_run(ops_test.model.applications["etcd"].units[0], jcmd)
    assert "rocks" in action.results["stdout"]

    nscmd = "{} ETCDCTL_API=2 /snap/bin/etcd.etcdctl get nested/data".format(
        " ".join(certs)
    )
    action = await _unit_run(ops_test.model.applications["etcd"].units[0], nscmd)
    assert "works" in action.results["stdout"]


async def validate_running_snap_daemon(ops_test: OpsTest):
    cmd = "systemctl is-active snap.etcd.etcd"
    action = await _unit_run(ops_test.model.applications["etcd"].units[0], cmd)
    assert "active" in action.results["stdout"]


async def test_snapshot_restore(ops_test: OpsTest):
    # Make sure there is only 1 unit of etcd running
    for unit in ops_test.model.applications["etcd"].units:
        if len(ops_test.model.applications["etcd"].units) > 1:
            await unit.destroy()
            await ops_test.model.wait_for_idle(wait_for_active=True, timeout=60 * 60)

    await load_data(ops_test)
    assert await is_data_present(ops_test, "v2")
    assert await is_data_present(ops_test, "v3")

    leader = await _get_leader(ops_test.model.applications["etcd"].units)

    filenames = {}
    for dataset in ["v2", "v3"]:
        action = await leader.run_action("snapshot", **{"keys-version": dataset})
        await action.wait()
        log.info(action.status)
        log.info(action.results)
        assert action.status == "completed"
        await leader.scp_from(action.results["snapshot"]["path"], ".")
        filenames[dataset] = os.path.basename(action.results["snapshot"]["path"])

    await delete_data(ops_test)
    assert not await is_data_present(ops_test, "v2")
    assert not await is_data_present(ops_test, "v3")

    # Below code is better but waiting for python-libjuju #654 fix, can't attach binary files yet due to the bug
    # with open(filenames["v2"], mode='rb') as file:
    #     ops_test.model.applications["etcd"].attach_resource("snapshot", filenames["v2"], file)

    await ops_test.model.wait_for_idle(wait_for_active=True, timeout=60 * 60)

    await ops_test.juju(
        "attach-resource", "etcd", "snapshot={}".format(filenames["v2"])
    )

    leader = await _get_leader(ops_test.model.applications["etcd"].units)
    action = await leader.run_action("restore")
    await action.wait()
    log.info(action.status)
    log.info(action.results)
    await ops_test.model.wait_for_idle(wait_for_active=True, timeout=60 * 60)

    assert action.status == "completed"
    assert await is_data_present(ops_test, "v2")
    assert not await is_data_present(ops_test, "v3")

    # Below code is better but waiting for python-libjuju #654 fix, can't attach binary files yet due to the bug
    # with open(filenames["v3"], mode='rb') as file:
    #     ops_test.model.applications["etcd"].attach_resource("snapshot", filenames["v3"], file)

    await ops_test.model.wait_for_idle(wait_for_active=True, timeout=60 * 60)

    await ops_test.juju(
        "attach-resource", "etcd", "snapshot={}".format(filenames["v3"])
    )

    leader = await _get_leader(ops_test.model.applications["etcd"].units)
    action = await leader.run_action("restore")
    await action.wait()
    log.info(action.status)
    log.info(action.results)
    await ops_test.model.wait_for_idle(wait_for_active=True, timeout=60 * 60)

    assert action.status == "completed"
    assert not await is_data_present(ops_test, "v2")
    assert await is_data_present(ops_test, "v3")


async def load_data(ops_test: OpsTest):
    leader = await _get_leader(ops_test.model.applications["etcd"].units)
    cmd = "{} ETCDCTL_API=2 /snap/bin/etcdctl set /etcd2key etcd2value".format(
        " ".join(certs)
    )
    await _unit_run(leader, cmd)
    cmd = "{} ETCDCTL_API=3 /snap/bin/etcdctl --endpoints=http://localhost:4001 put etcd3key etcd3value".format(
        " ".join(certs[3:])
    )
    await _unit_run(leader, cmd)


async def is_data_present(ops_test: OpsTest, version: str):
    leader = await _get_leader(ops_test.model.applications["etcd"].units)
    if version == "v2":
        cmd = "{} ETCDCTL_API=2 /snap/bin/etcdctl ls".format(" ".join(certs))
        action = await _unit_run(leader, cmd)
        log.info(action.status)
        log.info(action.results)
        return (
            "etcd2key" in action.results["stdout"]
            if "stdout" in action.results
            else False
        )
    elif version == "v3":
        cmd = '{} ETCDCTL_API=3 /snap/bin/etcdctl --endpoints=http://localhost:4001 get "" --prefix --keys-only'.format(
            " ".join(certs[3:])
        )
        action = await _unit_run(leader, cmd)
        log.info(action.status)
        log.info(action.results)
        return (
            "etcd3key" in action.results["stdout"]
            if "stdout" in action.results
            else False
        )
    return False


async def delete_data(ops_test: OpsTest):
    leader = await _get_leader(ops_test.model.applications["etcd"].units)
    cmd = "{} ETCDCTL_API=2 /snap/bin/etcdctl rm /etcd2key".format(" ".join(certs))
    await _unit_run(leader, cmd)

    cmd = "{} ETCDCTL_API=3 /snap/bin/etcdctl --endpoints=http://localhost:4001 del etcd3key".format(
        " ".join(certs[3:])
    )
    await _unit_run(leader, cmd)
