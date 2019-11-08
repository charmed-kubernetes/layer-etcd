#!/usr/local/sbin/charm-env python3

import os
import re
import shlex
import subprocess
import sys

from charms import layer

from charmhelpers.core.hookenv import (
    action_get,
    action_set,
    action_fail,
    action_name
)


def action_fail_now(*args, **kw):
    '''Call action_fail() and exit immediately.

    '''
    action_fail(*args, **kw)
    sys.exit(0)


def etcdctl_path():
    '''Return path to etcdctl binary.

    '''
    if os.path.isfile('/snap/bin/etcd.etcdctl'):
        return '/snap/bin/etcd.etcdctl'
    return 'etcdctl'


def etcdctl(cmd, etcdctl_api='3', endpoints=':4001', **kw):
    '''Call etcdctl with ``cmd`` as the command-line args.

    '''
    opts = layer.options('tls-client')

    # etcd 2.x.x
    env = os.environ.copy()
    env['ETCDCTL_CA_FILE'] = opts['ca_certificate_path']
    env['ETCDCTL_CERT_FILE'] = opts['server_certificate_path']
    env['ETCDCTL_KEY_FILE'] = opts['server_key_path']

    # etcd 3.x.x
    env['ETCDCTL_CACERT'] = opts['ca_certificate_path']
    env['ETCDCTL_CERT'] = opts['server_certificate_path']
    env['ETCDCTL_KEY'] = opts['server_key_path']

    if etcdctl_api:
        env['ETCDCTL_API'] = etcdctl_api

    etcdctl_cmd = etcdctl_path()
    if endpoints:
        etcdctl_cmd += ' --endpoints={}'.format(endpoints)

    args = shlex.split(etcdctl_cmd) + shlex.split(cmd)
    return subprocess.check_output(
        args, env=env, stderr=subprocess.STDOUT, **kw).decode("utf-8").strip()


def etcdctl_version():
    '''Return etcdctl version.

    '''
    output = etcdctl("--version", etcdctl_api=None, endpoints=None)
    first_line = output.split('\n')[0]
    version = first_line.split(' ')[-1]
    return version.strip()


def requires_etcd_version(version_regex, human_version=None):
    '''Decorator that enforces a specific version of etcdctl be present.

    The decorated function will only be executed if the required version
    of etcdctl is present. Otherwise, action_fail() will be called and
    the process will exit immediately.

    '''
    def wrap(f):
        def wrapped_f(*args):
            version = etcdctl_version()
            if not re.match(version_regex, version):
                required_version = human_version or version_regex
                action_fail_now(
                    'This action requires etcd version {}'.format(
                        required_version))
            f(*args)
        return wrapped_f
    return wrap


requires_etcd_v2 = requires_etcd_version(r'2\..*', human_version='2.x')
requires_etcd_v3 = requires_etcd_version(r'3\..*', human_version='3.x')


@requires_etcd_v3
def alarm_disarm():
    '''Call `etcdctl alarm disarm`.

    '''
    try:
        output = etcdctl('alarm disarm')
        action_set(dict(output=output))
    except subprocess.CalledProcessError as e:
        action_fail_now(e.output)


@requires_etcd_v3
def alarm_list():
    '''Call `etcdctl alarm list`.

    '''
    try:
        output = etcdctl('alarm list')
        action_set(dict(output=output))
    except subprocess.CalledProcessError as e:
        action_fail_now(e.output)


@requires_etcd_v3
def compact():
    '''Call `etcdctl compact`.

    '''
    def get_latest_revision():
        try:
            output = etcdctl('endpoint status --write-out="json"')
        except subprocess.CalledProcessError as e:
            action_fail_now(
                'Failed to determine latest revision for '
                'compaction: {}'.format(e))

        m = re.search(r'"revision":(\d*)', output)
        if not m:
            action_fail_now(
                "Failed to get revision from 'endpoint status' "
                "output: {}".format(output))
        return m.group(1)

    revision = action_get('revision') or get_latest_revision()
    physical = 'true' if action_get('physical') else 'false'
    command = 'compact {} --physical={}'.format(revision, physical)
    try:
        output = etcdctl(command)
        action_set(dict(output=output))
    except subprocess.CalledProcessError as e:
        action_fail_now(e.output)


@requires_etcd_v3
def defrag():
    '''Call `etcdctl defrag`.

    '''
    try:
        output = etcdctl('defrag')
        action_set(dict(output=output))
    except subprocess.CalledProcessError as e:
        action_fail_now(e.output)


if __name__ == '__main__':
    ACTIONS = {
        'alarm-disarm': alarm_disarm,
        'alarm-list': alarm_list,
        'compact': compact,
        'defrag': defrag,
    }

    action = action_name()
    ACTIONS[action]()
