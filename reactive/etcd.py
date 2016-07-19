#!/usr/bin/python3

from charms.reactive import when
from charms.reactive import when_any
from charms.reactive import when_not
from charms.reactive import is_state
from charms.reactive import set_state
from charms.reactive import remove_state
from charms.reactive import hook

from charms.templating.jinja2 import render

from charmhelpers.core.hookenv import status_set as hess
from charmhelpers.core.hookenv import log
from charmhelpers.core.hookenv import is_leader
from charmhelpers.core.hookenv import leader_set
from charmhelpers.core.hookenv import leader_get
from charmhelpers.core.hookenv import resource_get

from charmhelpers.core.hookenv import open_port
from charmhelpers.core.hookenv import close_port
from charmhelpers.core.hookenv import unit_get
from charmhelpers.core import hookenv
from charmhelpers.core import host
from charmhelpers.core import unitdata
from charmhelpers.fetch import apt_update
from charmhelpers.fetch import apt_install

from etcdctl import EtcdCtl
from etcdctl import get_connection_string
from etcd_databag import EtcdDatabag

from pwd import getpwnam
from shlex import split
from subprocess import check_call
from subprocess import CalledProcessError
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
    status_set('active', health['status'])


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
    status_set('maintenance', 'Installing etcd.')

    codename = host.lsb_release()['DISTRIB_CODENAME']

    try:
        etcd_path = resource_get('etcd')
        etcdctl_path = resource_get('etcdctl')
    # Not obvious but this blocks juju 1.25 clients
    except NotImplementedError:
        status_set('blocked', 'This charm requires the resource feature available in juju 2+')  # noqa
        return

    if not etcd_path or not etcdctl_path:
        if codename == 'xenial':
            # edge case where archive allows us a nice fallback on xenial
            status_set('maintenance', 'Attempting install of etcd from apt')
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
            return
        else:
            # edge case
            status_set('blocked', 'Missing Resource: see README')
    else:
        install(etcd_path, '/usr/bin/etcd')
        install(etcdctl_path, '/usr/bin/etcdctl')

        host.add_group('etcd')

        if not host.user_exists('etcd'):
            host.adduser('etcd')
            host.add_user_to_group('etcd', 'etcd')

        os.makedirs('/var/lib/etcd/', exist_ok=True)
        etcd_uid = getpwnam('etcd').pw_uid

        os.chmod('/var/lib/etcd/', 0o775)
        os.chown('/var/lib/etcd/', etcd_uid, -1)

        # Trusty was the EOL for upstart, render its template if required
        if codename == 'trusty':
            render('upstart', '/etc/init/etcd.conf',
                   {}, owner='root', group='root')
            set_state('etcd.installed')
            return

        if not os.path.exists('/etc/systemd/system/etcd.service'):
            render('systemd', '/etc/systemd/system/etcd.service',
                   {}, owner='root', group='root')
            # This will cause some greif if its been run before
            # so allow it to be chatty and fail if we ever re-render
            # and attempt re-enablement.
            try:
                check_call(split('systemctl enable etcd'))
            except CalledProcessError:
                pass

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
            msg = 'Waiting for unit to complete registration'
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
        status_set('blocked', 'Cluster not healthy')
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
        status_set('blocked', 'Cluster not healthy')
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


def status_set(status, message):
    ''' This is a fun little hack to give me the leader in status output
        without taking it over '''
    if is_leader():
        message = "(leader) {}".format(message)
    hess(status, message)
