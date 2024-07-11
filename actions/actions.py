#!/usr/local/sbin/charm-env python3

import re
import subprocess
import sys

from charmhelpers.core.hookenv import action_fail, action_get, action_name, action_set
from etcdctl import EtcdCtl

CTL = EtcdCtl()


def action_fail_now(*args, **kw):
    """Call action_fail() and exit immediately."""
    action_fail(*args, **kw)
    sys.exit(0)


def requires_etcd_version(version_regex, human_version=None):
    """Decorator that enforces a specific version of etcdctl be present.

    The decorated function will only be executed if the required version
    of etcdctl is present. Otherwise, action_fail() will be called and
    the process will exit immediately.

    """

    def wrap(f):
        def wrapped_f(*args):
            version = CTL.version()
            if not re.match(version_regex, version):
                required_version = human_version or version_regex
                action_fail_now(
                    "This action requires etcd version {}".format(required_version)
                )
            f(*args)

        return wrapped_f

    return wrap


requires_etcd_v2 = requires_etcd_version(r"2\..*", human_version="2.x")
requires_etcd_v3 = requires_etcd_version(r"3\..*", human_version="3.x")


@requires_etcd_v3
def alarm_disarm():
    """Call `etcdctl alarm disarm`."""
    try:
        output = CTL.run("alarm disarm")
        action_set(dict(output=output))
    except subprocess.CalledProcessError as e:
        action_fail_now(e.output)


@requires_etcd_v3
def alarm_list():
    """Call `etcdctl alarm list`."""
    try:
        output = CTL.run("alarm list")
        action_set(dict(output=output))
    except subprocess.CalledProcessError as e:
        action_fail_now(e.output)


@requires_etcd_v3
def compact():
    """Call `etcdctl compact`."""

    def get_latest_revision():
        try:
            output = CTL.run("endpoint status --write-out json")
        except subprocess.CalledProcessError as e:
            action_fail_now(
                "Failed to determine latest revision for " "compaction: {}".format(e)
            )

        m = re.search(r'"revision":(\d*)', output)
        if not m:
            action_fail_now(
                "Failed to get revision from 'endpoint status' "
                "output: {}".format(output)
            )
        return m.group(1)

    revision = action_get("revision") or get_latest_revision()
    physical = "true" if action_get("physical") else "false"
    command = "compact {} --physical={}".format(revision, physical)
    try:
        output = CTL.run(command)
        action_set(dict(output=output))
    except subprocess.CalledProcessError as e:
        action_fail_now(e.output)


@requires_etcd_v3
def defrag():
    """Call `etcdctl defrag`."""
    try:
        output = CTL.run("defrag")
        action_set(dict(output=output))
    except subprocess.CalledProcessError as e:
        action_fail_now(e.output)


def health():
    """Call etcdctl cluster-health"""
    try:
        output = CTL.cluster_health(True)
        action_set(dict(output=output))
    except subprocess.CalledProcessError as e:
        action_fail_now(e.output)


if __name__ == "__main__":
    ACTIONS = {
        "alarm-disarm": alarm_disarm,
        "alarm-list": alarm_list,
        "compact": compact,
        "defrag": defrag,
        "health": health,
    }

    action = action_name()
    ACTIONS[action]()
