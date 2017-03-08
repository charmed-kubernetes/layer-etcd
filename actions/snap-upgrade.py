#!/usr/bin/env python3

from charms.layer import snap
from charmhelpers.core.hookenv import action_get
from charmhelpers.core.hookenv import action_set
from charmhelpers.core.hookenv import action_fail
from charmhelpers.core.hookenv import config
from charmhelpers.core.hookenv import log
from charms.reactive import is_state

# from charmhelpers.core.host import chdir

from datetime import datetime

from subprocess import check_call
from subprocess import CalledProcessError

from shlex import split

import os
import shutil
import sys
import tempfile


# Define some dict's containing paths of files we expect to see in
# scenarios

deb_paths = {'config': ['/etc/ssl/etcd/ca.crt',
                        '/etc/ssl/etcd/server.crt',
                        '/etc/ssl/etcd/server.key',
                        '/etc/ssl/etcd/client.crt',
                        '/etc/ssl/etcd/client.key',
                        '/etc/default/etcd',
                        '/lib/systemd/system/etcd.service'],
             'data': ['/var/lib/etcd/default']}

# Snappy only cares about the config objects. Data validation will come
# at a later date. We can etcdctl ls / and then verify the data made it
# post migration.
snap_paths = {'config': ['/var/snap/etcd/common/etcd.conf',
                         '/var/snap/etcd/common/server.crt',
                         '/var/snap/etcd/common/server.key',
                         '/var/snap/etcd/common/ca.crt',
                         '/var/snap/etcd/common/client.crt',
                         '/var/snap/etcd/common/client.key']}


def create_migration_backup(backup_package=''):
    ''' Backup existing Etcd config/data paths if found and create a
    tarball consisting of that discovered configuration '''

    datestring = datetime.strftime(datetime.now(), '%Y%m%d_%H%M%S')

    if not backup_package:
        pkg = '/home/ubuntu/etcd_migration_{}'
        backup_package = pkg.format(datestring)

    if os.path.exists(backup_package):
        msg = 'Backup package exists: {}'.format(backup_package)
        action_set({'fail.message': msg})
        return False

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a temporary path to perform the backup, and date the contents.
        dated_path = "{0}/etcd_migration_{1}".format(tmpdir, datestring)
        os.makedirs(dated_path, exist_ok=True)

        # backup all the configuration data
        for p in deb_paths['config']:
            if os.path.exists(p):
                shutil.copy(p, dated_path)
            else:
                log('Skipping copy for: {} - file not found'.format(p), 'WARN')

        # backup the actual state of etcd's data
        for p in deb_paths['data']:
            if os.path.exists(p):
                cmd = 'rsync -avzp {} {}'.format(p, dated_path)
                check_call(split(cmd))

        try:
            # Create the tarball in its final location
            shutil.make_archive(backup_package, 'gztar', tmpdir)
        except Exception as ex:
            action_set({'fail.message': ex.message})
            return False
    log('Created backup {}'.format(backup_package))
    return True


def install_snap(channel, classic=False):
    ''' Handle installation of snaps, both from resources and from the snap
    store. The only indicator we need is classic mode and the channel '''
    snap.install('etcd', channel=channel, classic=classic)


def deb_to_snap_migration():
    has_migrated = has_migrated_from_deb()
    if not has_migrated:
        try:
            cmd = '/snap/bin/etcd.ingest'
            check_call(split(cmd))
        except CalledProcessError as cpe:
            log('Error encountered during ingest.', 'ERROR')
            log('Error message: {}'.format(cpe.message))
            action_fail('Migration failed')


def purge_deb_files():
    log('Purging deb configuration files post migration', 'INFO')
    cmd = 'apt purge etcd'
    check_call(split(cmd))
    for f in deb_paths['config']:
        log('Removing file {}'.format(f), 'INFO')
        os.remove(f)


def has_migrated_from_deb():
    for p in snap_paths:
        # helpful when debugging
        log("Scanning for file: {} {}".format(p, os.path.exists(p)), 'DEBUG')
        if not os.path.exists(p):
            return False
    return True

if __name__ == '__main__':
    # Control flow of the action
    backup_package = action_get('target')
    backup = action_get('backup')
    channel = config('channel')

    if backup:
        backup_status = create_migration_backup(backup_package)
        if not backup_status:
            action_fail('Failed creating the backup. Refusing to proceed.')
            sys.exit(0)

    if not is_state('etcd.deb.migrated'):
        install_snap('ingest/stable', True)
        deb_to_snap_migration()
    install_snap(channel, False)
    purge_deb_files()

