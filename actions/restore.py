#!/usr/local/sbin/charm-env python3

import random
from charms import layer
from charms.templating.jinja2 import render
from charmhelpers.core import unitdata
from charmhelpers.core import hookenv
from charmhelpers.core.hookenv import function_fail
from charmhelpers.core.hookenv import action_get
from charmhelpers.core.hookenv import action_set
from charmhelpers.core.hookenv import config
from charmhelpers.core.hookenv import log
from charmhelpers.core.hookenv import resource_get
from charmhelpers.core.hookenv import is_leader
from charmhelpers.core.hookenv import _run_atstart
from charmhelpers.core.hookenv import _run_atexit
from charmhelpers.core.host import chdir
from charmhelpers.core.host import service_start
from charmhelpers.core.host import service_stop
from etcd_lib import get_ingress_address
from etcdctl import EtcdCtl
from etcd_databag import EtcdDatabag
from shlex import split
from subprocess import check_call
from subprocess import check_output
from subprocess import CalledProcessError
from subprocess import Popen
from subprocess import PIPE
from datetime import datetime
from uuid import uuid4
import hashlib
import os
import sys
import time
import yaml

# Import charm layers and start reactive
layer.import_layer_libs()
_run_atstart()

opts = layer.options('etcd')

DATESTAMP = datetime.strftime(datetime.now(), '%Y%m%d-%H%M%S')
ARCHIVE = "etcd-data-{}.tar.gz".format(DATESTAMP)

unit_name = os.getenv('JUJU_UNIT_NAME').replace('/', '')
ETCD_DATA_DIR = '{}/{}.etcd'.format(opts['etcd_data_dir'], unit_name)
if not os.path.isdir(ETCD_DATA_DIR):
    ETCD_DATA_DIR = opts['etcd_data_dir']

ETCD_PORT = config('management_port')
CLUSTER_ADDRESS = get_ingress_address('cluster')
SKIP_BACKUP = action_get('skip-backup')
SNAPSHOT_ARCHIVE = resource_get('snapshot')
TARGET_PATH = action_get('target')


def preflight_check():
    ''' Check preconditions for data restoration '''
    if not is_leader():
        function_fail('This action can only be run on the leader unit')
        sys.exit(0)
    if not SNAPSHOT_ARCHIVE:
        function_fail({'result.failed': 'Missing snapshot. See: README.md'})
        sys.exit(0)


def render_backup():
    ''' Backup existing data in the event of restoration on a dirty unit. '''
    if not os.path.isdir(ETCD_DATA_DIR) and SKIP_BACKUP:
        msg = "Backup set to True, but no data found to backup"
        action_set({'backup.error': msg})
    if not os.path.isdir(ETCD_DATA_DIR):
        return

    with chdir(ETCD_DATA_DIR):
        if not SKIP_BACKUP:
            log('Backing up existing data found in {}'.format(ETCD_DATA_DIR))
            archive_path = "{}/{}".format(TARGET_PATH, ARCHIVE)
            cmd = 'tar cvf {0} {1}'.format(archive_path, '.')
            check_call(split(cmd))
            backup_sum = shasum_file(archive_path)
            action_set({'backup.path': archive_path,
                        'backup.sha256sum': backup_sum})


def unpack_resource():
    ''' Grab the resource path, and unpack it into $PATH '''
    cmd = "tar xvf {0} -C {1}".format(SNAPSHOT_ARCHIVE, ETCD_DATA_DIR)
    check_call(split(cmd))


def is_v3_backup():
    ''' See if the backup file does not contain a wal file indicating a v3 backup '''
    # ETCD v3 doesn't contain a wal file which leads to below command to fail
    # With that we can differentiate between v3 and v2&v1
    cmd = "tar -tvf {0} --wildcards '*/wal'".format(SNAPSHOT_ARCHIVE)
    try:
        check_call(split(cmd))
    except CalledProcessError:
        return True
    return False


def restore_v3_backup():
    ''' Apply a v3 backup '''
    cmd = "mkdir -p /root/tmp/restore-v3"
    check_call(split(cmd))

    cmd = "tar xvf {0} -C /root/tmp/restore-v3".format(SNAPSHOT_ARCHIVE)
    check_call(split(cmd))

    configfile = open('/var/snap/etcd/common/etcd.conf.yml', "r")
    config = yaml.safe_load(configfile)
    # Use the insecure 4001 port we have open in our deployment
    environ = dict(os.environ, ETCDCTL_API="3")
    cmd = "/snap/bin/etcdctl --endpoints=http://localhost:4001 snapshot " \
          "restore /root/tmp/restore-v3/db --skip-hash-check " \
          "--data-dir='/root/tmp/restore-v3/etcd' " \
          "--initial-cluster='{}' --initial-cluster-token='{}' " \
          "--initial-advertise-peer-urls='{}' --name='{}'"

    if 'initial-cluster' in config and config['initial-cluster']:
        # configuration contains initilization params
        cmd = cmd.format(config['initial-cluster'],
                         config['initial-cluster-token'],
                         config['initial-advertise-peer-urls'],
                         config['name'])
    else:
        # configuration does not contain initilization params
        # probably coming from an etcd upgrades from etcd2
        initial_cluster = '{}=https://{}:2380'.format(config['name'], CLUSTER_ADDRESS)
        initial_cluster_token = CLUSTER_ADDRESS
        initial_urls = 'https://{}:2380'.format(CLUSTER_ADDRESS)
        cmd = cmd.format(initial_cluster,
                         initial_cluster_token,
                         initial_urls,
                         config['name'])

    configfile.close()
    check_call(split(cmd), env=environ)

    # Make sure we do not have anything left from any old deployments
    cmd = "rm -rf {}/member".format(config['data-dir'])
    check_call(split(cmd))

    cmd = "cp -r /root/tmp/restore-v3/etcd/member {}".format(config['data-dir'])
    check_call(split(cmd))

    # Clean up
    cmd = "rm -rf /root/tmp/restore-v3"
    check_call(split(cmd))


def start_etcd_forked():
    ''' Start the etcd daemon temporarily to initiate new cluster details '''
    raw = "/snap/etcd/current/bin/etcd -data-dir={0} -force-new-cluster --enable-v2"
    cmd = raw.format(ETCD_DATA_DIR)
    proc = Popen(split(cmd), stdout=PIPE, stderr=PIPE)
    return proc.pid


def pkill_etcd(pid=''):
    ''' Kill the temporary forked etcd daemon '''
    # cmd = 'pkill etcd'
    if pid:
        cmd = 'kill -9 {}'.format(pid)
    else:
        cmd = 'pkill etcd'

    check_call(split(cmd))


def probe_forked_etcd():
    ''' Block until the forked etcd instance has started and return'''
    output = b""
    loop = 0
    MAX_WAIT = 10

    while b"http://localhost" not in output:
        try:
            output = check_output(split('/snap/bin/etcd.etcdctl member list'))
            loop = loop + 1
        except:
            log('Still waiting on forked etcd instance...')
            output = b""
            loop = loop + 1
        time.sleep(1)
        if loop > MAX_WAIT:
            raise TimeoutError("Timed out waiting for forked etcd.")


def reconfigure_client_advertise():
    ''' Reconfigure the backup to use host network addresses for client advertise
        instead of the assumed localhost addressing '''

    loop = 0
    MAX_WAIT = 10

    while loop < MAX_WAIT:
        try:
            cmd = "/snap/bin/etcd.etcdctl member list"
            members = check_output(split(cmd), env={"ETCDCTL_API": "2"})
            member_id = members.split(b':')[0].decode('utf-8')
            break
        except CalledProcessError as ex:
            loop = loop + 1
            log(
                "{}/{} member list failed during reconfiguring client advertise, retrying...".format(
                    loop, MAX_WAIT
                ),
                "WARNING",
            )
            if loop == MAX_WAIT:
                log(
                    "All member list tries failed during reconfiguring client advertise! Raising...",
                    "ERROR",
                )
                raise Exception('All member list tries failed') from ex
            time.sleep(1)

    raw_update = "/snap/bin/etcd.etcdctl member update {0} https://{1}:{2}"
    update_cmd = raw_update.format(member_id, CLUSTER_ADDRESS, ETCD_PORT)
    check_call(split(update_cmd), env={"ETCDCTL_API": "2"})


def shasum_file(filepath):
    ''' Compute the SHA256sum of a file for verification purposes '''
    BUF_SIZE = 65536  # 64kb chunk size
    shasum = hashlib.sha256()
    with open(filepath, 'rb') as fp:
        while True:
            data = fp.read(BUF_SIZE)
            if not data:
                break
            shasum.update(data)
    return shasum.hexdigest()


def dismantle_cluster():
    """Disconnect other cluster members.

    This is a preparation step before restoring snapshot on the cluster.
    """
    log('Disconnecting cluster members')
    etcdctl = EtcdCtl()
    etcd_conf = EtcdDatabag()

    my_name = etcd_conf.unit_name
    endpoint = 'https://{}:{}'.format(etcd_conf.cluster_address,
                                      etcd_conf.port)
    for name, data in etcdctl.member_list(endpoint).items():
        if name != my_name:
            log('Disconnecting {}'.format(name), hookenv.DEBUG)
            loop = 0
            MAX_WAIT = 10

            while loop < MAX_WAIT:
                try:
                    etcdctl.unregister(data['unit_id'], endpoint)
                    break
                except EtcdCtl.CommandFailed as ex:
                    # Back-off timer to let cluster settle
                    log("Disconnecting {} failed, retrying...".format(name), "WARNING")
                    if loop == MAX_WAIT:
                        log(
                            "All tries for disconnecting the member {} failed! Raising...".format(name),
                            "ERROR",
                        )
                        raise Exception('Disconnecting a member from cluster failed') from ex
                    time.sleep(1)

    etcd_conf.cluster_state = 'new'
    conf_path = os.path.join(etcd_conf.etcd_conf_dir, "etcd.conf.yml")
    render('etcd3.conf', conf_path, etcd_conf.__dict__, owner='root',
           group='root')


def rebuild_cluster():
    """Signal other etcd units to rejoin new cluster."""
    log('Requesting peer members to rejoin cluster')
    rejoin_request = uuid4().hex
    hookenv.leader_set(force_rejoin=rejoin_request)


if __name__ == '__main__':
    log('Performing etcd snapshot restore')
    preflight_check()
    render_backup()
    dismantle_cluster()
    service_stop(opts['etcd_daemon_process'])
    if is_v3_backup():
        log("v3 backup detected, restoring...", "INFO")
        restore_v3_backup()
    else:
        log("v2 backup detected, restoring...", "INFO")
        unpack_resource()
        pid = start_etcd_forked()
        probe_forked_etcd()
        reconfigure_client_advertise()
        pkill_etcd(pid)
    service_start(opts['etcd_daemon_process'])
    rebuild_cluster()
    _run_atexit()
