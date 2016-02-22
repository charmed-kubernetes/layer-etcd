
from charms.reactive import when
from charms.reactive import when_not
from charms.reactive import set_state
from charms.reactive import remove_state
from charms.reactive import hook

from charmhelpers.core.hookenv import status_set
from charmhelpers.core.hookenv import is_leader
from charmhelpers.core.hookenv import leader_set
from charmhelpers.core.hookenv import leader_get

from charmhelpers.core.hookenv import config
from charmhelpers.core.hookenv import unit_get
from charmhelpers.core import host
from charmhelpers.core.unitdata import kv
from charmhelpers.core import templating
from charmhelpers import fetch

from etcd import EtcdHelper


@hook('config-changed')
def remove_states():
    cfg = config()
    if cfg.changed('source-sum'):
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


@when('cluster.available')
def cluster_update(cluster):
    '''' Runs on cluster "disturbed" mode. Each unit is declaring their
         participation. If you're not the leader, you can ignore this'''
    etcd_helper = EtcdHelper()
    unit = { cluster.unit_name(): {
            'public_address': cluster.public_address(),
            'private_address': cluster.private_address(),
            'port': cluster.port(),
            'unit_name': cluster.unit_name(),
            'management_port': cluster.management_port()}}
    # Store data about every peer we have seen. this may be useful later
    etcd_helper.cluster_data(unit)
    if is_leader():
        # store and leader-set the new cluster string
        leader_set({'cluster': etcd_helper.cluster_string()})


@hook('leader-settings-changed')
def update_cluster_string():
    print(leader_get('cluster'))
    remove_state('etcd.configured')

@when_not('etcd.installed')
def install_etcd():
    source = config('source-path')
    sha = config('source-sum')

    status_set('maintenance', 'Installing etcd.')
    etcd_helper = EtcdHelper()
    etcd_helper.fetch_and_install(source, sha)
    set_state('etcd.installed')


@when('etcd.installed')
@when_not('etcd.configured')
def configure_etcd():
    etcd_helper = EtcdHelper()
    cluster_data = {'private_address': unit_get('private-address')}
    cluster_data['unit_name'] = etcd_helper.unit_name
    if is_leader():
        status_set('maintenance', "I am the leader, configuring single node")
        etcd_helper = EtcdHelper()
        cluster_data['token'] = etcd_helper.cluster_token()
        cluster_data['cluster_state'] = 'existing'
        cluster_data['cluster'] = etcd_helper.cluster_string()
        cluster_data['leader_address'] = unit_get('private-address')
        leader_set(cluster_data)
        cluster_data['cluster_state'] = 'new'
    else:
        cluster_data['token'] = leader_get('token')
        cluster_data['cluster_state'] = leader_get('cluster_state')
        cluster_data['cluster'] = etcd_helper.cluster_string(leader_get('cluster'))
        cluster_data['leader_address'] = leader_get('leader_address')
        status_set('maintenance', 'registering unit with etcd-leader')
        etcd_helper.register(cluster_data)

    templating.render('upstart', '/etc/init/etcd.conf',
                      cluster_data, owner='root', group='root')

    host.service('restart', 'etcd')
    set_state('etcd.configured')

@when('etcd.configured')
def service_messaging():
    if is_leader():
        status_set('active', 'Etcd leader running')
    else:
        status_set('active', 'Etcd follower running')
