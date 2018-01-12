#!/usr/bin/env python3

from charms import layer
from charmhelpers.core.hookenv import action_fail
from charmhelpers.core.hookenv import action_get
from charmhelpers.core.hookenv import action_set
from charmhelpers.core.hookenv import config
from charmhelpers.core.hookenv import log
from charmhelpers.core.hookenv import unit_get
from charmhelpers.core.hookenv import resource_get
from charmhelpers.core.host import chdir
from charmhelpers.core.host import service_start
from charmhelpers.core.host import service_stop
from shlex import split
from subprocess import check_call
from subprocess import check_output
from subprocess import CalledProcessError
from subprocess import Popen
from subprocess import PIPE
from datetime import datetime
import hashlib
import os
import sys
import time
import yaml

opts = layer.options('etcd')

DATESTAMP = datetime.strftime(datetime.now(), '%Y%m%d-%H%M%S')
ARCHIVE = "etcd-data-{}.tar.gz".format(DATESTAMP)

unit_name = os.getenv('JUJU_UNIT_NAME').replace('/', '')
ETCD_DATA_DIR = '{}/{}.etcd'.format(opts['etcd_data_dir'], unit_name)
if not os.path.isdir(ETCD_DATA_DIR):
    ETCD_DATA_DIR = opts['etcd_data_dir']

ETCD_PORT = config('management_port')
PRIVATE_ADDRESS = unit_get('private-address')
SKIP_BACKUP = action_get('skip-backup')
SNAPSHOT_ARCHIVE = resource_get('snapshot')
TARGET_PATH = action_get('target')


def preflight_check():
    ''' Check preconditions for data restoration '''
    if not SNAPSHOT_ARCHIVE:
        action_fail({'result.failed': 'Missing snapshot. See: README.md'})
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
    ''' See if the backup file contains a db file indicating a v3 backup '''
    cmd = "tar -tvf {0} --wildcards '*/db'".format(SNAPSHOT_ARCHIVE)
    try:
        check_call(split(cmd))
    except CalledProcessError:
        return False
    return True


def restore_v3_backup():
    ''' Apply a v3 backup '''
    cmd = "mkdir -p /var/tmp/restore-v3"
    check_call(split(cmd))

    cmd = "tar xvf {0} -C /var/tmp/restore-v3".format(SNAPSHOT_ARCHIVE)
    check_call(split(cmd))

    configfile = open('/var/snap/etcd/common/etcd.conf.yml', "r")
    config = yaml.load(configfile)
    # Use the insecure 4001 port we have open in our deployment
    environ = dict(os.environ, ETCDCTL_API="3")
    cmd = "/snap/bin/etcdctl --endpoints=http://localhost:4001 snapshot " \
          "restore /var/tmp/restore-v3/db --skip-hash-check " \
          "--data-dir='/var/tmp/restore-v3/etcd' " \
          "--initial-cluster='{}' --initial-cluster-token='{}' " \
          "--initial-advertise-peer-urls='{}' --name='{}'"
    cmd = cmd.format(config['initial-cluster'],
                     config['initial-cluster-token'],
                     config['initial-advertise-peer-urls'],
                     config['name'])
    configfile.close()
    check_call(split(cmd), env=environ)

    # Make sure we do not have anything left from any old deployments
    cmd = "rm -rf /var/snap/etcd/current/member"
    check_call(split(cmd))

    cmd = "cp -r /var/tmp/restore-v3/etcd/member /var/snap/etcd/current/"
    check_call(split(cmd))

    # Clean up
    cmd = "rm -rf /var/tmp/restore-v3"
    check_call(split(cmd))


def start_etcd_forked():
    ''' Start the etcd daemon temporarily to initiate new cluster details '''
    raw = "/snap/etcd/current/bin/etcd -data-dir={0} -force-new-cluster"
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
    cmd = "/snap/bin/etcd.etcdctl member list"
    members = check_output(split(cmd))
    member_id = members.split(b':')[0].decode('utf-8')

    raw_update = "/snap/bin/etcd.etcdctl member update {0} http://{1}:{2}"
    update_cmd = raw_update.format(member_id, PRIVATE_ADDRESS, ETCD_PORT)
    check_call(split(update_cmd))


def stop_etcd():
    ''' Stop the etcd service, delivered by snap or by deb'''
    try:
        service_stop('snap.etcd.etcd')
        log('Stopped service: snap.etcd.etcd')
    except:
        log('Failed to stop snap.etcd.etcd')

    try:
        service_stop('etcd')
        log('Stopped service: etcd')
    except:
        log('Failed to stop service: etcd')


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


if __name__ == '__main__':
    preflight_check()
    stop_etcd()
    render_backup()
    if is_v3_backup():
        restore_v3_backup()
    else:
        unpack_resource()
        pid = start_etcd_forked()
        probe_forked_etcd()
        reconfigure_client_advertise()
        pkill_etcd(pid)
    service_start(opts['etcd_daemon_process'])
