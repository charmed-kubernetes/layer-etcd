from typing import List
from pytest_operator.plugin import OpsTest
from juju.unit import Unit
import logging
import os
from pathlib import Path
import pytest

log = logging.getLogger(__name__)

v2_env = [
    "ETCDCTL_API=2",
    "ETCDCTL_KEY_FILE=/var/snap/etcd/common/client.key",
    "ETCDCTL_CERT_FILE=/var/snap/etcd/common/client.crt",
    "ETCDCTL_CA_FILE=/var/snap/etcd/common/ca.crt",
]
v3_env = [
    "ETCDCTL_API=3",
    "ETCDCTL_KEY=/var/snap/etcd/common/client.key",
    "ETCDCTL_CERT=/var/snap/etcd/common/client.crt",
    "ETCDCTL_CACERT=/var/snap/etcd/common/ca.crt",
]

etcdctl_2 = f"{' '.join(v2_env)} /snap/bin/etcdctl --endpoint=https://127.0.0.1:2379"
etcdctl_3 = f"{' '.join(v3_env)} /snap/bin/etcdctl --endpoints=https://127.0.0.1:2379"


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

    jcmd = f"{etcdctl_2} set juju rocks"
    await _unit_run(ops_test.model.applications["etcd"].units[0], jcmd)

    nscmd = f"{etcdctl_2} set nested/data works"
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
        cmd = f"{etcdctl_2} cluster-health"
        action = await _unit_run(unit, cmd)
        assert "unhealthy" not in action.results["stdout"]
        assert "unavailable" not in action.results["stdout"]


async def test_leader_knows_all_members(ops_test: OpsTest):
    leader = await _get_leader(ops_test.model.applications["etcd"].units)
    cmd = f"{etcdctl_2} member list"
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
    jcmd = f"{etcdctl_2} get juju"
    action = await _unit_run(ops_test.model.applications["etcd"].units[0], jcmd)
    assert "rocks" in action.results["stdout"]

    nscmd = f"{etcdctl_2} get nested/data"
    action = await _unit_run(ops_test.model.applications["etcd"].units[0], nscmd)
    assert "works" in action.results["stdout"]


async def validate_running_snap_daemon(ops_test: OpsTest):
    cmd = "systemctl is-active snap.etcd.etcd"
    action = await _unit_run(ops_test.model.applications["etcd"].units[0], cmd)
    assert "active" in action.results["stdout"]


async def test_snapshot_restore(ops_test: OpsTest, tmp_path: Path):
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
        await leader.scp_from(action.results["snapshot"]["path"], tmp_path)
        filenames[dataset] = tmp_path / os.path.basename(
            action.results["snapshot"]["path"]
        )

    await delete_data(ops_test)
    assert not await is_data_present(ops_test, "v2")
    assert not await is_data_present(ops_test, "v3")

    with filenames["v2"].open(mode="rb") as file:
        ops_test.model.applications["etcd"].attach_resource(
            "snapshot", filenames["v2"], file
        )

    await ops_test.model.wait_for_idle(wait_for_active=True, timeout=60 * 60)

    leader = await _get_leader(ops_test.model.applications["etcd"].units)
    action = await leader.run_action("restore")
    await action.wait()
    log.info(action.status)
    log.info(action.results)
    await ops_test.model.wait_for_idle(wait_for_active=True, timeout=60 * 60)

    assert action.status == "completed"
    assert await is_data_present(ops_test, "v2")
    assert not await is_data_present(ops_test, "v3")

    with filenames["v3"].open(mode="rb") as file:
        ops_test.model.applications["etcd"].attach_resource(
            "snapshot", filenames["v3"], file
        )

    await ops_test.model.wait_for_idle(wait_for_active=True, timeout=60 * 60)

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
    cmd = f"{etcdctl_2} set /etcd2key etcd2value"
    await _unit_run(leader, cmd)
    cmd = f"{etcdctl_3} put etcd3key etcd3value"
    await _unit_run(leader, cmd)


async def is_data_present(ops_test: OpsTest, version: str):
    leader = await _get_leader(ops_test.model.applications["etcd"].units)
    if version == "v2":
        cmd = f"{etcdctl_2} ls"
        action = await _unit_run(leader, cmd)
        log.info(action.status)
        log.info(action.results)
        return (
            "etcd2key" in action.results["stdout"]
            if "stdout" in action.results
            else False
        )
    elif version == "v3":
        cmd = f'{etcdctl_3} get "" --prefix --keys-only'
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
    cmd = f"{etcdctl_2} rm /etcd2key"
    await _unit_run(leader, cmd)

    cmd = f"{etcdctl_3} del etcd3key"
    await _unit_run(leader, cmd)
