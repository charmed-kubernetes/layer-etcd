
from charms.reactive import when
from charms.reactive import when_not
from charms.reactive import set_state
from charms.reactive import remove_state
from charms.reactive import hook

from charmhelpers.core.hookenv import status_set
from charmhelpers.core.hookenv import is_leader
from charmhelpers.core.hookenv import config
from charmhelpers.core.hookenv import unit_get
from charmhelpers.core.unitdata import kv
from charmhelpers import fetch

from etcd import EtcdHelper

@hook('leader-elected')
def remove_configuration_state():
    remove_state('etcd.configured')

@when_not('etcd.installed')
def install_etcd():
    source = config('source-path')
    sha = config('source-sum')

    status_set('maintenance', 'Installing etcd.')
    etcd_helper = EtcdHelper()
    etcd_helper.fetch_and_install(source, sha)
    set_state('etcd.installed')

@when_not('etcd.configured')
def configure_etcd():

    if is_leader():
        status_set('maintenance', "I am the leader, configuring single node")
        etcd_helper = EtcdHelper()
        cluster_data = {'token': etcd_helper.cluster_token()}
        cluster_data['cluster_state'] = 'existing'
        cluster_data['cluster'] = etcd_helper.cluster_string()
        cluster_data['leader_address'] = unit_get('private-address')
        print(cluster_data)
        leader_set('cluster_data')

    templating.render('etcd.conf.jinja2', '/etc/init/etcd.conf',
                      cluster_data, owner='root', group='root')

    host.service('restart', 'etcd')
    if leader_status:
        status_set('active', 'Etcd leader running')
    else:
        status_set('active', 'Etcd follower running')
