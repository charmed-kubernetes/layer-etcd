#!/usr/local/sbin/charm-env python3

from charms.layer import snap
from charmhelpers.core import unitdata
from charmhelpers.core.hookenv import action_get
from charmhelpers.core.hookenv import action_set
from charmhelpers.core.hookenv import action_fail
from charmhelpers.core.hookenv import config
from charmhelpers.core.hookenv import log
from charms.reactive import is_state
from charms.reactive import remove_state
from charms.reactive import set_state

# from charmhelpers.core.host import chdir

from datetime import datetime
from subprocess import call
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
                        '/etc/default/etcd'],
             'data': ['/var/lib/etcd/default']}

# Snappy only cares about the config objects. Data validation will come
# at a later date. We can etcdctl ls / and then verify the data made it
# post migration.
snap_paths = {'config': ['/var/snap/etcd/common/etcd.conf.yml',
                         '/var/snap/etcd/common/server.crt',
                         '/var/snap/etcd/common/server.key',
                         '/var/snap/etcd/common/ca.crt'],
              'client': ['/var/snap/etcd/common/client.crt',
                         '/var/snap/etcd/common/client.key'],
              'common':  '/var/snap/etcd/common'}


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
        os.makedirs(dated_path)

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

        for key_path in snap_paths['client']:
            chmod = "chmod 644 {}".format(key_path)
            call(split(chmod))
        cmod = "chmod 755 {}".format(snap_paths['common'])
        call(split(cmod))


def purge_deb_files():
    probe_package_command = 'dpkg --list etcd'
    return_code = call(split(probe_package_command))
    if return_code != 0:
        # The return code from dpkg --list when the package is
        # non existant
        action_set({'dpkg.list.message': 'dpkg probe return_code > 0',
                    'skip.package.purge': 'True'})
        return
    log('Purging deb configuration files post migration', 'INFO')
    cmd = 'apt-get purge -y etcd'
    try:
        check_call(split(cmd))
    except CalledProcessError as cpe:
        action_fail({'apt.purge.message': cpe.message})

    for f in deb_paths['config']:
        try:
            log('Removing file {}'.format(f), 'INFO')
            os.remove(f)
        except FileNotFoundError:
            k = 'purge.missing.{}'.format(os.path.basename(f))
            msg = 'Did not purge {}. File not found.'.format(f)
            action_set({k: msg})
        except:
            k = 'purge.error.{}'.format(f)
            msg = 'Failed to purge {}. Manual removal required.'.format(k)
            action_set({k: msg})


def has_migrated_from_deb():
    for p in snap_paths['config']:
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
    if channel == "auto":
        channel = "3.4/stable"

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
    remove_state('etcd.installed')
    set_state('snap.installed.etcd')
    remove_state('etcd.pillowmints')
    unitdata.kv().flush()
    call(['hooks/config-changed'])
