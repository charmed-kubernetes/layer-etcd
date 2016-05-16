#!/usr/bin/python3

from charms.reactive import when
from charms.reactive import when_any
from charms.reactive import when_not
from charms.reactive import set_state
from charms.reactive import remove_state
from charms.reactive import hook

from charmhelpers.core.hookenv import status_set as hess
from charmhelpers.core.hookenv import is_leader
from charmhelpers.core.hookenv import leader_set
from charmhelpers.core.hookenv import leader_get
from charmhelpers.core.hookenv import resource_get

from charmhelpers.core.hookenv import config
from charmhelpers.core.hookenv import log
from charmhelpers.core.hookenv import open_port
from charmhelpers.core.hookenv import unit_get
from charmhelpers.core import host
from charmhelpers.core import templating
from charmhelpers.core import unitdata
from charmhelpers.fetch import apt_update
from charmhelpers.fetch import apt_install

from etcd import EtcdHelper
from pwd import getpwnam
from shlex import split
from shutil import copyfile
from subprocess import check_call
from subprocess import CalledProcessError

import os


@when('etcd.configured')
def check_cluster_health():
    # We have an opportunity to report on the cluster health every 5
    # minutes, lets leverage that.
    etcd_helper = EtcdHelper()
    health = etcd_helper.get_cluster_health_output()
    status_set('active', health)


@hook('upgrade-charm')
def remove_states():
    # upgrade-charm issues when we rev resources and the charm. Assume an upset
    remove_state('etcd.installed')
    remove_state('etcd.configured')


@hook('leader-elected')
def remove_configuration_state():
    remove_state('etcd.configured')
    etcd_helper = EtcdHelper()
    cluster_data = {'token': etcd_helper.cluster_token()}
    cluster_data['cluster_state'] = 'existing'
    cluster_data['cluster'] = etcd_helper.cluster_string()
    cluster_data['leader_address'] = unit_get('private-address')
    leader_set(cluster_data)


@when_any('config.changed.port', 'config.changed.management_port')
def update_port_mappings():
    open_port(config('port'))
    open_port(config('management_port'))
    remove_state('etcd.configured')


@when('cluster.declare_self')
def cluster_declaration(cluster):
    etcd = EtcdHelper()
    for unit in cluster.list_peers():
        cluster.provide_cluster_details(scope=unit,
                                        public_address=etcd.public_address,
                                        port=etcd.port,
                                        unit_name=etcd.unit_name)

    remove_state('cluster.declare_self')


@when('cluster.joining')
def cluster_update(cluster):
    '''' Runs on cluster "disturbed" mode. Each unit is declaring their
         participation. If you're not the leader, you can ignore this'''
    etcd = EtcdHelper()
    etcd.cluster_data({cluster.unit_name():
                       {'private_address': cluster.private_address(),
                        'public_address': cluster.public_address(),
                        'unit_name': cluster.unit_name()}})

    if is_leader():
        # store and leader-set the new cluster string
        leader_set({'cluster': etcd.cluster_string()})

    remove_state('etcd.configured')
    remove_state('cluster.joining')


@when('cluster.departed')
def remove_unit_from_cluster(cluster):
    etcd = EtcdHelper()
    etcd.remove_unit_from_cache(cluster.unit_name)
    # trigger template and service restart
    remove_state('etcd.configured')
    # end of peer-departing event
    remove_state('cluster.departed')


@when('db.connected')
def send_connection_details(client):
    etcd = EtcdHelper()
    data = etcd.cluster_data()
    hosts = []
    for unit in data:
        hosts.append(data[unit]['private_address'])
    client.provide_connection_string(hosts, config('port'))


@when('proxy.connected')
def send_cluster_details(proxy):
    etcd = EtcdHelper()
    proxy.provide_cluster_string(etcd.cluster_string())


@hook('leader-settings-changed')
def update_cluster_string():
    # When the leader makes a broadcast, assume an upset and prepare for
    # service restart
    remove_state('etcd.configured')


@when_not('etcd.installed')
def install_etcd():
    status_set('maintenance', 'Installing etcd.')

    codename = host.lsb_release()['DISTRIB_CODENAME']

    try:
        etcd_path = resource_get('etcd')
        etcdctl_path = resource_get('etcdctl')
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
                rmtree('/var/lib/etcd/')
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
            templating.render('upstart', '/etc/init/etcd.conf',
                              {}, owner='root', group='root')
            set_state('etcd.installed')
            return

        if not os.path.exists('/etc/systemd/system/etcd.service'):
            templating.render('systemd', '/etc/systemd/system/etcd.service',
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
@when_not('etcd.configured')
def configure_etcd():
    ''' There's a lot going on in here. Minimally stating, we are gaging the
    state of the world and broadcasting that if we are the leader. Otherwise we
    are looking to leader data, and what we can get from config to generate our
    services config during the registration sequence '''
    # This library has some convience methods to generate cluster strings from
    # relation data, and other 'helpers'. Use it to generate as much shared
    # config as possible before we diverge for leader/follower
    etcd_helper = EtcdHelper()
    cluster_data = {'private_address': unit_get('private-address')}
    cluster_data['unit_name'] = etcd_helper.unit_name
    cluster_data['management_port'] = config('management_port')
    cluster_data['port'] = config('port')

    # TLS - this is a relatively new concern, and i'd like to keep a
    # close eye on it until this branch settles.
    ssl_path = '/etc/ssl/etcd'
    cluster_data['ca_certificate'] = '{}/ca.pem'.format(ssl_path)
    cluster_data['server_certificate'] = '{}/server.pem'.format(ssl_path)
    cluster_data['server_key'] = '{}/server-key.pem'.format(ssl_path)

    # The leader broadcasts the cluster settings, as the leader controls the
    # state of the cluster. This assumes the leader is always initializing new
    # clusters, and may need to be adapted later to support existing cluster
    # states.
    if is_leader():
        status_set('maintenance', "I am the leader, configuring single node")
        cluster_data['token'] = etcd_helper.cluster_token()
        cluster_data['cluster_state'] = 'existing'
        cluster_data['cluster'] = etcd_helper.cluster_string()
        cluster_data['leader_address'] = unit_get('private-address')
        # Actually broadcast that gnarly dictionary
        leader_set(cluster_data)
        # leader assumes new? seems to work.
        cluster_data['cluster_state'] = 'new'
    else:
        status_set('maintenance', 'registering unit with etcd-leader')
        cluster_data['token'] = leader_get('token')
        cluster_data['cluster_state'] = leader_get('cluster_state')
        cluster_data['cluster'] = etcd_helper.cluster_string()
        cluster_data['leader_address'] = leader_get('leader_address')
        # self registration provided via the helper class
        etcd_helper.register(cluster_data)
    # Now that we have configured for the upset, lets render our environment
    # details/files and prepare to do some work

    templating.render('defaults', '/etc/default/etcd',
                      cluster_data, owner='root', group='root')

    host.service('restart', 'etcd')
    set_state('etcd.configured')


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
        copyfile(keypath.format(server),
                 '{}/server-key.pem'.format(etcd_ssl_path))
    else:
        copyfile(keypath.format(unit_get('public-address')),
                 '{}/server-key.pem'.format(etcd_ssl_path))

    set_state('etcd.ssl.placed')


@when('easyrsa installed')
@when_not('etcd.tls.opensslconfig.modified')
def inject_swarm_tls_template():
    """
    layer-tls installs a default OpenSSL Configuration that is incompatibile
    with how etcd expects TLS keys to be generated. We will append what
    we need to the x509-type, and poke layer-tls to regenerate.
    """
    if is_leader():
        status_set('maintenance', 'Reconfiguring SSL PKI configuration')

        log('Updating EasyRSA3 OpenSSL Config')
        openssl_config = 'easy-rsa/easyrsa3/x509-types/server'

        with open(openssl_config, 'r') as f:
            existing_template = f.readlines()

        # use list comprehension to enable clients,server usage for
        # certificate with the docker/swarm daemons.
        xtype = [w.replace('serverAuth', 'serverAuth, clientAuth') for w in existing_template]  # noqa
        with open(openssl_config, 'w+') as f:
            f.writelines(xtype)

        set_state('etcd.tls.opensslconfig.modified')
        set_state('easyrsa configured')


@when_not('etcd.pillowmints')
def render_default_user_ssl_exports():
    with open('/home/ubuntu/.bash_aliases', 'w+') as fp:
        fp.writelines(['export ETCDCTL_KEY_FILE=/etc/ssl/etcd/server-key.pem\n',  # noqa
                       'export ETCDCTL_CERT_FILE=/etc/ssl/etcd/server.pem\n',
                       'export ETCDCTL_CA_FILE=/etc/ssl/etcd/ca.pem\n'])

    set_state('etcd.pillowmints')


def install(src, tgt):
    ''' This method wraps the bash 'install' command '''
    return check_call(split('install {} {}'.format(src, tgt)))


def status_set(status, message):
    ''' This is a fun little hack to give me the leader in status output
        without taking it over '''
    if is_leader():
        message = "(leader) {}".format(message)
    hess(status, message)
