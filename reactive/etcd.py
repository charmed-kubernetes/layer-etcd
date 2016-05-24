#!/usr/bin/python3

from charms.reactive import when
from charms.reactive import when_not
from charms.reactive import set_state
from charms.reactive import is_state
from charms.reactive import remove_state
from charms.reactive import hook

from charmhelpers.core.hookenv import status_set
from charmhelpers.core.hookenv import is_leader
from charmhelpers.core.hookenv import leader_set
from charmhelpers.core.hookenv import leader_get
from charmhelpers.core.hookenv import resource_get

from charmhelpers.core.hookenv import config
from charmhelpers.core.hookenv import unit_get
from charmhelpers.core import host
from charmhelpers.core import templating
from charmhelpers.fetch import apt_update
from charmhelpers.fetch import apt_install

from etcd import EtcdHelper
from pwd import getpwnam
from subprocess import check_call
from subprocess import CalledProcessError
from shlex import split
from shutil import rmtree

import os


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
                rmtree('/var/lib/etcd/default')
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
@when_not('etcd.configured')
def configure_etcd():
    etcd_helper = EtcdHelper()
    cluster_data = {'private_address': unit_get('private-address')}
    cluster_data['unit_name'] = etcd_helper.unit_name
    cluster_data['management_port'] = config('management_port')
    cluster_data['port'] = config('port')
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

    codename = host.lsb_release()['DISTRIB_CODENAME']
    if codename == 'trusty':
        templating.render('upstart', '/etc/init/etcd.conf',
                          cluster_data, owner='root', group='root')
    else:
        templating.render('defaults', '/etc/default/etcd',
                          cluster_data, owner='root', group='root')

    host.service('restart', 'etcd')
    set_state('etcd.configured')


@when('etcd.configured')
def service_messaging():
    ''' I really like seeing the leadership status as my default message for
        etcd so I know who the MVP is. This method reflects that. '''
    if is_leader():
        status_set('active', 'Etcd leader running')
    else:
        status_set('active', 'Etcd follower running')


def install(src, tgt):
    ''' This method wraps the bash 'install' command '''
    return check_call(split('install {} {}'.format(src, tgt)))
