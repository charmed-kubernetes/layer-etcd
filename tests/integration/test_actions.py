import os
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
    resources = {"snapshot": "snapshot.tar.gz"}
    await ops_test.model.deploy(charm, resources=resources)
    await ops_test.model.add_relation("easyrsa:client", "etcd:certificates")
    await ops_test.model.wait_for_idle(wait_for_active=True, timeout=60 * 60)


async def test_snapshot_restore(ops_test: OpsTest):
    await load_data(ops_test)
    assert await is_data_present(ops_test, "v2")
    assert await is_data_present(ops_test, "v3")

    filenames = {}
    for dataset in ["v2", "v3"]:
        action = (
            await ops_test.model.applications["etcd"]
            .units[0]
            .run_action("snapshot", **{"keys-version": dataset})
        )
        await action.wait()
        assert action.status == "completed"
        await ops_test.model.applications["etcd"].units[0].scp_from(
            action.results["snapshot"]["path"], "."
        )
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

    action = await ops_test.model.applications["etcd"].units[0].run_action("restore")
    await action.wait()
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

    action = await ops_test.model.applications["etcd"].units[0].run_action("restore")
    await action.wait()
    assert action.status == "completed"
    assert not await is_data_present(ops_test, "v2")
    assert await is_data_present(ops_test, "v3")


async def load_data(ops_test: OpsTest):
    cmd = "{} ETCDCTL_API=2 /snap/bin/etcdctl set /etcd2key etcd2value".format(
        " ".join(certs)
    )
    await ops_test.model.applications["etcd"].units[0].run(cmd)
    cmd = "{} ETCDCTL_API=3 /snap/bin/etcdctl --endpoints=http://localhost:4001 put etcd3key etcd3value".format(
        " ".join(certs[3:])
    )
    await ops_test.model.applications["etcd"].units[0].run(cmd)


async def is_data_present(ops_test: OpsTest, version: str):
    if version == "v2":
        cmd = "{} ETCDCTL_API=2 /snap/bin/etcdctl ls".format(" ".join(certs))
        action = await ops_test.model.applications["etcd"].units[0].run(cmd)
        return (
            "etcd2key" in action.results["Stdout"]
            if "Stdout" in action.results
            else False
        )
    elif version == "v3":
        cmd = '{} ETCDCTL_API=3 /snap/bin/etcdctl --endpoints=http://localhost:4001 get "" --prefix --keys-only'.format(
            " ".join(certs[3:])
        )
        action = await ops_test.model.applications["etcd"].units[0].run(cmd)
        return (
            "etcd3key" in action.results["Stdout"]
            if "Stdout" in action.results
            else False
        )
    return False


async def delete_data(ops_test: OpsTest):
    cmd = "{} ETCDCTL_API=2 /snap/bin/etcdctl rm /etcd2key".format(" ".join(certs))
    await ops_test.model.applications["etcd"].units[0].run(cmd)
    cmd = "{} ETCDCTL_API=3 /snap/bin/etcdctl --endpoints=http://localhost:4001 del etcd3key".format(
        " ".join(certs[3:])
    )
    await ops_test.model.applications["etcd"].units[0].run(cmd)
