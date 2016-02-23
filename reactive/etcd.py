
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
from charmhelpers.core import templating

from etcd import EtcdHelper
from subprocess import CalledProcessError

@hook('config-changed')
def remove_states():
    # Matt - this is where it's not immutable :)
    cfg = config()
    if cfg.changed('source-sum') or cfg.changed('source-url'):
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


@when('cluster.joining')
def cluster_update(cluster):
    '''' Runs on cluster "disturbed" mode. Each unit is declaring their
         participation. If you're not the leader, you can ignore this'''
    etcd_helper = EtcdHelper()
    unit = {cluster.unit_name(): {
            'public_address': cluster.public_address(),
            'private_address': cluster.private_address(),
            'unit_name': cluster.unit_name()}}
    # Store data about every peer we have seen. this may be useful later
    etcd_helper.cluster_data(unit)
    remove_state('etcd.configured')
    if is_leader():
        # store and leader-set the new cluster string
        leader_set({'cluster': etcd_helper.cluster_string()})
        remove_state('cluster.joining')




@when('cluster.departed')
def remove_unit_from_cluster(cluster):
    etcd = EtcdHelper()
    etcd.remove_unit_from_cache(cluster.unit_name)
    # trigger template and service restart
    remove_state('etcd.configured')
    # end of peer-departing event
    remove_state('cluster.departed')


@hook('leader-settings-changed')
def update_cluster_string():
    # When the leader makes a broadcast, assume an upset and prepare for
    # service restart
    remove_state('etcd.configured')


@when_not('etcd.installed')
def install_etcd():
    source = config('source-url')
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
    # The leader broadcasts the cluster settings, as the leader controls the
    # state of the cluster. This assumes the leader is always initializing new
    # clusters, and may need to be adapted later to support existing cluster
    # states.
    if is_leader():
        status_set('maintenance', "I am the leader, configuring single node")
        etcd_helper = EtcdHelper()
        cluster_data['token'] = etcd_helper.cluster_token()
        cluster_data['cluster_state'] = 'existing'
        cluster_data['cluster'] = etcd_helper.cluster_string()
        cluster_data['leader_address'] = unit_get('private-address')
        # Actually broadcast that gnarly dictionary
        leader_set(cluster_data)
        # leader assumes new? seems to work.
        cluster_data['cluster_state'] = 'new'
    else:
        cluster_data = {'private_address': unit_get('private-address')}
        cluster_data['unit_name'] = etcd_helper.unit_name
        cluster_data['token'] = leader_get('token')
        cluster_data['cluster_state'] = leader_get('cluster_state')
        cluster_data['cluster'] = etcd_helper.cluster_string()
        cluster_data['leader_address'] = leader_get('leader_address')
        status_set('maintenance', 'registering unit with etcd-leader')
        # self registration provided via the helper class
        etcd_helper.register(cluster_data)

    # Always nuking and regenerating this script.. perhaps this should
    # move to a @when_modified decorated method.
    templating.render('upstart', '/etc/init/etcd.conf',
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
