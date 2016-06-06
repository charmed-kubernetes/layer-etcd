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
from charmhelpers.core.hookenv import is_leader
from charmhelpers.core.hookenv import leader_set
from charmhelpers.core.hookenv import leader_get
from charmhelpers.core.hookenv import resource_get

from charmhelpers.core.hookenv import config
from charmhelpers.core.hookenv import open_port
from charmhelpers.core.hookenv import unit_get
from charmhelpers.core import host
from charmhelpers.core import unitdata
from charmhelpers.fetch import apt_update
from charmhelpers.fetch import apt_install

from etcdctl import EtcdCtl
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


# @when('db.connected')
# def send_connection_details(client):
#     etcd = EtcdHelper()
#     data = etcd.cluster_data()
#     hosts = []
#     for unit in data:
#         hosts.append(data[unit]['private_address'])
#     client.provide_connection_string(hosts, config('port'))
#
# #
# @when('proxy.connected')
# def send_cluster_details(proxy):
#     etcd = EtcdHelper()
#     proxy.provide_cluster_string(etcd.cluster_string())
#

@when_not('etcd.installed')
def install_etcd():
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
@when_not('leadership.is_leader')
@when_not('etcd.registered')
def register_node_with_leader():
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
@when('cluster.joined')
@when('leadership.is_leader')
@when_not('etcd.leader.configured')
def initialize_new_leader():
    bag = EtcdDatabag()
    bag.token = bag.token
    bag.cluster_state = 'new'
    bag.cluster = "{}=https://{}:{}".format(bag.unit_name,
                                            bag.private_address,
                                            bag.management_port)
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
    leader_set({'token': bag.token,
                'leader_address': "https://{}:{}".format(bag.private_address,
                                                         bag.port),
                'cluster': bag.cluster})

    # finish bootstrap delta and set configured state
    set_state('etcd.leader.configured')


@when('etcd.ssl.placed')
@when_not('leadership.is_leader')
@when_not('client-credentials-relayed')
def relay_client_credentials():

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
def unregister(cluster):
    etcdctl = EtcdCtl()
    if is_state('leadership.is_leader'):
        for node in cluster.nodes():
            etcdctl.unregister(cluster.get_guid(node))
    cluster.dismiss()


def install(src, tgt):
    ''' This method wraps the bash 'install' command '''
    return check_call(split('install {} {}'.format(src, tgt)))


def status_set(status, message):
    ''' This is a fun little hack to give me the leader in status output
        without taking it over '''
    if is_leader():
        message = "(leader) {}".format(message)
    hess(status, message)
