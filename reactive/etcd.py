#!/usr/bin/python3

from charms.reactive import when
from charms.reactive import when_any
from charms.reactive import when_not
from charms.reactive import is_state
from charms.reactive import set_state
from charms.reactive import remove_state
from charms.reactive import hook

from charms.templating.jinja2 import render

from charmhelpers.core.hookenv import log
from charmhelpers.core.hookenv import leader_set
from charmhelpers.core.hookenv import leader_get
from charmhelpers.core.hookenv import status_set
from charmhelpers.core.hookenv import storage_get

from charmhelpers.core.hookenv import application_version_set
from charmhelpers.core.hookenv import open_port
from charmhelpers.core.hookenv import close_port
from charmhelpers.core.hookenv import unit_get
from charmhelpers.core import hookenv
from charmhelpers.core import host
from charmhelpers.core import unitdata
from charmhelpers.fetch import apt_update
from charmhelpers.fetch import apt_install
from charmhelpers.contrib.charmsupport import nrpe

from etcdctl import EtcdCtl
from etcdctl import get_connection_string
from etcd_databag import EtcdDatabag

from shlex import split
from subprocess import check_call
from subprocess import check_output
from tlslib import client_cert
from tlslib import client_key

import os
import charms.leadership  # noqa
import shutil
import time

# this was in the layer-tls readme
set_state('tls.client.authorization.required')


@when_any('etcd.registered', 'etcd.leader.configured')
def check_cluster_health():
    ''' report on the cluster health every 5 minutes'''
    etcdctl = EtcdCtl()
    health = etcdctl.cluster_health()

    # Determine if the unit is healthy or unhealthy
    if 'healthy' in health['status']:
        unit_health = "Healthy"
    else:
        unit_health = "Unhealthy"

    # Determine units peer count, and surface 0 by default
    try:
        peers = len(etcdctl.member_list())
    except Exception:
        peers = 0

    status_message = "{0} with {1} known peers.".format(unit_health, peers)
    status_set('active', status_message)


@when('etcd.installed')
def set_app_version():
    ''' Surface the etcd application version on juju status '''
    # Format of version output at the time of writing
    # etcd Version: 2.2.5
    # Git SHA: Not provided (use ./build instead of go build)
    # Go Version: go1.6rc2
    # Go OS/Arch: linux/amd64
    cmd = ['etcd', '-version']
    version = check_output(cmd).split(b'\n')[0].split(b':')[-1].lstrip()
    application_version_set(version)


@hook('upgrade-charm')
def remove_states():
    # upgrade-charm issues when we rev resources and the charm. Assume an upset
    remove_state('etcd.installed')


@when('etcd.installed')
@when('leadership.is_leader')
@when_any('config.changed.port', 'config.changed.management_port')
def leader_config_changed():
    ''' The leader executes the runtime configuration update for the cluster,
    as it is the controlling unit. Will render config, close and open ports and
    restart the etcd service.'''
    configuration = hookenv.config()
    previous_port = configuration.previous('port')
    log('Previous port: {0}'.format(previous_port))
    previous_mgmt_port = configuration.previous('management_port')
    log('Previous management port: {0}'.format(previous_mgmt_port))
    if previous_port and previous_mgmt_port:
        bag = EtcdDatabag()
        etcdctl = EtcdCtl()
        members = etcdctl.member_list()
        # Iterate over all the members in the list.
        for unit_name in members:
            # Grab the previous peer url and replace the management port.
            peer_urls = members[unit_name]['peer_urls']
            log('Previous peer url: {0}'.format(peer_urls))
            old_port = ':{0}'.format(previous_mgmt_port)
            new_port = ':{0}'.format(configuration.get('management_port'))
            url = peer_urls.replace(old_port, new_port)
            # Update the member's peer_urls with the new ports.
            log(etcdctl.member_update(members[unit_name]['unit_id'], url))
        # Render just the leaders configuration with the new values.
        render('defaults', '/etc/default/etcd', bag.__dict__, owner='root',
               group='root')
        # Close the previous client port and open the new one.
        close_open_ports()
        leader_set({'leader_address':
                   get_connection_string([bag.private_address],
                                         bag.management_port)})
        host.service_restart('etcd')


@when('etcd.installed')
@when_not('leadership.is_leader')
@when_any('config.changed.port', 'config.changed.management_port')
def follower_config_changed():
    ''' Follower units need to render the configuration file, close and open
    ports, and restart the etcd service. '''
    bag = EtcdDatabag()
    log('Rendering defaults file for {0}'.format(bag.unit_name))
    # Render the follower's configuration with the new values.
    render('defaults', '/etc/default/etcd', bag.__dict__, owner='root',
           group='root')
    # Close the previous client port and open the new one.
    close_open_ports()
    host.service_restart('etcd')


@when('db.connected')
@when('etcd.ssl.placed')
@when('cluster.joined')
def send_cluster_connection_details(cluster, db):
    ''' Need to set the cluster connection string and
    the client key and certificate on the relation object. '''
    cert = leader_get('client_certificate')
    key = leader_get('client_key')
    ca = leader_get('certificate_authority')
    # Set the key, cert, and ca on the db relation
    db.set_client_credentials(key, cert, ca)

    port = hookenv.config().get('port')
    # Get all the peers participating in the cluster relation.
    members = cluster.get_peer_addresses()
    # Create a connection string with all the members on the configured port.
    connection_string = get_connection_string(members, port)
    # Set the connection string on the db relation.
    db.set_connection_string(connection_string)


@when('db.connected')
@when('etcd.ssl.placed')
def send_single_connection_details(db):
    ''' '''
    cert = leader_get('client_certificate')
    key = leader_get('client_key')
    ca = leader_get('certificate_authority')
    # Set the key and cert on the db relation
    db.set_client_credentials(key, cert, ca)

    bag = EtcdDatabag()
    # Get all the peers participating in the cluster relation.
    members = [bag.private_address]
    # Create a connection string with this member on the configured port.
    connection_string = get_connection_string(members, bag.port)
    # Set the connection string on the db relation.
    db.set_connection_string(connection_string)


@when('proxy.connected')
@when('etcd.ssl.placed')
@when_any('etcd.leader.configured', 'cluster.joined')
def send_cluster_details(proxy):
    ''' Attempts to send the peer cluster string to
    proxy units so they can join and act on behalf of the cluster. '''
    cert = leader_get('client_certificate')
    key = leader_get('client_key')
    ca = leader_get('certificate_authority')
    proxy.set_client_credentials(key, cert, ca)

    # format a list of cluster participants
    etcdctl = EtcdCtl()
    peers = etcdctl.member_list()
    cluster = []
    for peer in peers:
        thispeer = peers[peer]
        # Potential member doing registration. Default to skip
        if 'peer_urls' not in thispeer.keys() or not thispeer['peer_urls']:
            continue
        peer_string = "{}={}".format(thispeer['name'], thispeer['peer_urls'])
        cluster.append(peer_string)

    proxy.set_cluster_string(','.join(cluster))


@when_not('etcd.installed')
def install_etcd():
    ''' Attempt resource get on the "etcd" and "etcdctl" resources. If no
    resources are provided attempt to install from the archive only on the
    16.04 (xenial) series. '''

    status_set('maintenance', 'Installing etcd from apt.')
    pkg_list = ['etcd']
    apt_update()
    apt_install(pkg_list, fatal=True)
    # Stop the service and remove the defaults
    # I hate that I have to do this. Sorry short-lived local data #RIP
    # State control is to prevent upgrade-charm from nuking cluster
    # data.
    if not is_state('etcd.package.adjusted'):
        host.service('stop', 'etcd')
        if os.path.exists('/var/lib/etcd/default'):
            shutil.rmtree('/var/lib/etcd/default')
        set_state('etcd.package.adjusted')
    set_state('etcd.installed')


@when('etcd.installed')
@when('etcd.ssl.placed')
@when('cluster.joined')
@when_not('leadership.is_leader')
@when_not('etcd.registered')
def register_node_with_leader(cluster):
    '''
    Control flow mechanism to perform self registration with the leader.

    Before executing self registration, we must adhere to the nature of offline
    static turnup rules. If we find a GUID in the member list without peering
    information the unit will enter a race condition and must wait for a clean
    status output before we can progress to self registration.
    '''
    # We're going to communicate with the leader, and we need our bootstrap
    # startup string once.. TBD after that.
    etcdctl = EtcdCtl()
    bag = EtcdDatabag()
    # Assume a hiccup during registration and attempt a retry
    if bag.cluster_unit_id:
        bag.cluster = bag.registration_peer_string
        render('defaults', '/etc/default/etcd', bag.__dict__)
        host.service_restart('etcd')
        time.sleep(2)

    peers = etcdctl.member_list(leader_get('leader_address'))
    for unit in peers:
        if 'client_urls' not in peers[unit].keys():
            # we cannot register. State not attainable.
            msg = 'Waiting for unit to complete registration.'
            status_set('waiting', msg)
            return

    if not bag.cluster_unit_id:
        bag.leader_address = leader_get('leader_address')
        resp = etcdctl.register(bag.__dict__)
        if resp and 'cluster_unit_id' in resp.keys() and 'cluster' in resp.keys():  # noqa
            bag.cache_registration_detail('cluster_unit_id',
                                          resp['cluster_unit_id'])
            bag.cache_registration_detail('registration_peer_string',
                                          resp['cluster'])

            bag.cluster_unit_id = resp['cluster_unit_id']
            bag.cluster = resp['cluster']

    render('defaults', '/etc/default/etcd', bag.__dict__)
    host.service_restart('etcd')
    time.sleep(2)

    # Check health status before we say we are good
    etcdctl = EtcdCtl()
    status = etcdctl.cluster_health()
    if 'unhealthy' in status:
        status_set('blocked', 'Cluster not healthy.')
        return
    open_port(bag.port)
    set_state('etcd.registered')


@when('etcd.installed')
@when('etcd.ssl.placed')
@when('leadership.is_leader')
@when_not('etcd.leader.configured')
def initialize_new_leader():
    ''' Create an initial cluster string to bring up a single member cluster of
    etcd, and set the leadership data so the followers can join this one. '''
    bag = EtcdDatabag()
    bag.token = bag.token
    bag.cluster_state = 'new'
    cluster_connection_string = get_connection_string([bag.private_address],
                                                      bag.management_port)
    bag.cluster = "{}={}".format(bag.unit_name, cluster_connection_string)
    render('defaults', '/etc/default/etcd', bag.__dict__, owner='root',
           group='root')
    host.service_restart('etcd')

    # sorry, some hosts need this. The charm races with systemd and wins.
    time.sleep(2)

    # Check health status before we say we are good
    etcdctl = EtcdCtl()
    status = etcdctl.cluster_health()
    if 'unhealthy' in status:
        status_set('blocked', 'Cluster not healthy.')
        return
    # We have a healthy leader, broadcast initial data-points for followers
    open_port(bag.port)
    leader_connection_string = get_connection_string([bag.private_address],
                                                     bag.port)
    leader_set({'token': bag.token,
                'leader_address': leader_connection_string,
                'cluster': bag.cluster})

    # finish bootstrap delta and set configured state
    set_state('etcd.leader.configured')


@when('etcd.ssl.placed')
@when_not('leadership.is_leader')
@when_not('client-credentials-relayed')
def relay_client_credentials():
    ''' Write the client cert and key to the charm directory on followers. '''
    # offer a short circuit if we have already received broadcast
    # credentials for the cluster
    if leader_get('client_certificate') and leader_get('client_key'):
        with open('client.crt', 'w+') as fp:
            fp.write(leader_get('client_certificate'))
        with open('client.key', 'w+') as fp:
            fp.write(leader_get('client_key'))
        set_state('client-credentials-relayed')
        return


@when('leadership.is_leader')
@when('etcd.ssl.placed')
@when_not('client-credentials-relayed')
def broadcast_client_credentials():
    ''' As the leader, copy the client cert and key to the charm dir and set
    the contents as leader data.'''
    charm_dir = os.getenv('CHARM_DIR')
    client_cert(None, charm_dir)
    client_key(None, charm_dir)
    with open('client.crt') as fp:
        client_certificate = fp.read()
    with open('client.key') as fp:
        client_certificate_key = fp.read()
    leader_set({'client_certificate': client_certificate,
                'client_key': client_certificate_key})
    set_state('client-credentials-relayed')


@when('tls.server.certificate available')
@when_not('etcd.ssl.placed')
def install_etcd_certificates():
    ''' Copy the server cert and key to /etc/ssl/etcd and set the
    etcd.ssl.placed state. '''
    etcd_ssl_path = '/etc/ssl/etcd'
    if not os.path.exists(etcd_ssl_path):
        os.makedirs(etcd_ssl_path)

    kv = unitdata.kv()
    cert = kv.get('tls.server.certificate')
    with open('{}/server.pem'.format(etcd_ssl_path), 'w+') as f:
        f.write(cert)
    with open('{}/ca.pem'.format(etcd_ssl_path), 'w+') as f:
        f.write(leader_get('certificate_authority'))

    # schenanigans - each server makes its own key, when generating
    # the CSR. This is why its "magically" present.
    keypath = 'easy-rsa/easyrsa3/pki/private/{}.key'
    server = os.getenv('JUJU_UNIT_NAME').replace('/', '_')
    if os.path.exists(keypath.format(server)):
        shutil.copyfile(keypath.format(server),
                        '{}/server-key.pem'.format(etcd_ssl_path))
    else:
        shutil.copyfile(keypath.format(unit_get('public-address')),
                        '{}/server-key.pem'.format(etcd_ssl_path))

    set_state('etcd.ssl.placed')


@when_not('etcd.pillowmints')
def render_default_user_ssl_exports():
    ''' Add secure credentials to default user environment configs,
    transparently adding TLS '''
    evars = ['export ETCDCTL_KEY_FILE=/etc/ssl/etcd/server-key.pem\n',  # noqa
             'export ETCDCTL_CERT_FILE=/etc/ssl/etcd/server.pem\n',
             'export ETCDCTL_CA_FILE=/etc/ssl/etcd/ca.pem\n']

    with open('/home/ubuntu/.bash_aliases', 'w+') as fp:
        fp.writelines(evars)
    with open('/root/.bash_aliases', 'w+') as fp:
        fp.writelines(evars)
    set_state('etcd.pillowmints')


@when('cluster.departing')
@when('leadership.is_leader')
def unregister(cluster):
    ''' The leader will process the departing event and attempt unregistration
        for the departing unit. If the leader is departing, it will unregister
        all units prior to termination.
    '''
    etcdctl = EtcdCtl()
    peers = cluster.get_peers()
    members = etcdctl.member_list()
    for unit in peers:
        cluster_name = unit.replace('/', '')
        if cluster_name in members.keys():
            log("Unregistering {0}".format(unit))
            etcdctl.unregister(members[cluster_name]['unit_id'])
        else:
            log("Received removal for disconnected member {}".format(unit))
    cluster.dismiss()


@when('cluster.departing')
@when_not('leadership.is_leader')
def passive_dismiss_context(cluster):
    ''' All units undergo the departing phase. This is a no-op unless you
        are the leader '''
    cluster.dismiss()


@hook('data-storage-attached')
def format_and_mount_storage():
    ''' This allows users to request persistent volumes from the cloud provider
    for the purposes of disaster recovery. '''

    # Query juju for the information about the block storage
    device_info = storage_get()
    block = device_info['location']

    if volume_is_mounted(block):
        hookenv.log('Device is already attached to the system.')
        hookenv.log('Refusing to take action against {}'.format(block))

    # Format the device in non-interactive mode
    cmd = ['mkfs.ext4', device_info['location'], '-F']
    hookenv.log('Creating filesystem on {}'.format(device_info['location']))
    hookenv.log('With command: {}'.format(' '.join(cmd)))
    check_call(cmd)

    # Only attempt migration if directory exists
    if os.path.isdir('/var/lib/etcd/default'):
        hookenv.log('Detected existing data, migrating to new location.')
        # Migrate any existing data
        os.makedirs('/mnt/etcd-migrate', exist_ok=True)
        mount_volume(block, '/mnt/etcd-migrate')

        cmd = ['rsync', '-azp', '/var/lib/etcd/default', '/mnt/etcd-migrate/']
        hookenv.log('With command: {}'.format(' '.join(cmd)))
        check_call(cmd)

        unmount_path('/mnt/etcd-migrate')

    # halt etcd to perform the data-store migration
    host.service_stop('etcd')

    with open('/etc/fstab', 'r') as fp:
        contents = fp.readlines()

    found = 0
    # scan fstab for the device
    for line in contents:
        if block in line:
            found = found + 1

    # if device not in fstab, append so it persists through reboots
    if not found > 0:
        append = "{} /var/lib/etcd ext4 defaults 0 0".format(block)
        with open('/etc/fstab', 'a') as fp:
            fp.writelines([append])

    mount_volume(block, '/var/lib/etcd')
    # handle first run during early-attach storage, pre-config-changed hook.
    os.makedirs('/var/lib/etcd/default', exist_ok=True)

    # Finally re-establish etcd operation
    host.service_restart('etcd')


@when('nrpe-external-master.available')
@when_not('nrpe-external-master.initial-config')
def initial_nrpe_config(nagios=None):
    set_state('nrpe-external-master.initial-config')
    update_nrpe_config(nagios)


@when('etcd.installed')
@when('nrpe-external-master.available')
@when_any('config.changed.nagios_context',
          'config.changed.nagios_servicegroups')
def update_nrpe_config(unused=None):
    # List of systemd services that will be checked
    services = ('etcd',)

    # The current nrpe-external-master interface doesn't handle a lot of logic,
    # use the charm-helpers code for now.
    hostname = nrpe.get_nagios_hostname()
    current_unit = nrpe.get_nagios_unit_name()
    nrpe_setup = nrpe.NRPE(hostname=hostname, primary=False)
    nrpe.add_init_service_checks(nrpe_setup, services, current_unit)
    nrpe_setup.write()


def volume_is_mounted(volume):
    ''' Takes a hardware path and returns true/false if it is mounted '''
    cmd = ['df', '-t', 'ext4']
    out = check_output(cmd).decode('utf-8')
    return volume in out


def mount_volume(volume, location):
    ''' Takes a device path and mounts it to location '''
    cmd = ['mount', volume, location]
    hookenv.log("Mounting {0} to {1}".format(volume, location))
    check_call(cmd)


def unmount_path(location):
    ''' Unmounts a mounted volume at path '''
    cmd = ['umount', location]
    hookenv.log("Unmounting {0}".format(location))
    check_call(cmd)


def close_open_ports():
    ''' Close the previous port and open the port from configuration. '''
    configuration = hookenv.config()
    previous_port = configuration.previous('port')
    port = configuration.get('port')
    if previous_port is not None and previous_port != port:
        log('The port changed; closing {0} opening {1}'.format(previous_port,
            port))
        close_port(previous_port)
        open_port(port)


def install(src, tgt):
    ''' This method wraps the bash "install" command '''
    return check_call(split('install {} {}'.format(src, tgt)))
