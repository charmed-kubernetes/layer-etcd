# This entire file needs formatted and abstracted into a class

# In the older etcd charm there is 2 definite sets of data structures being
# used.
#
# {etcd1: {
#         'public_address': 127.0.0.1,
#         'private_address': 127.0.0.1,
#         'port': 4001,
#         'unit_name': etcd1,
#         'management_port': 7001)
#         }}

from charmhelpers.core.hookenv import unit_get
from charmhelpers.core.hookenv import is_leader
from charmhelpers.core.hookenv import leader_get
from charmhelpers.core import unitdata
from charmhelpers import fetch
from os import getenv
from path import path
import random
from shlex import split
import string
from subprocess import check_call


class EtcdHelper:

    def __init__(self, port=4001, management_port=7001):
        self.db = unitdata.kv()
        self.public_address = unit_get('public-address')
        self.private_address = unit_get('private-address')
        self.hook_data = unitdata.HookData()
        self.unit_name = getenv('JUJU_UNIT_NAME').replace('/', '')
        if port:
            self.port = port
        if management_port:
            self.management_port = management_port
        self.init_cluster_cache()

    def init_cluster_cache(self):
        if not self.db.get('etcd.cluster_data'):
            # initialize with ourself
            self.db.set('etcd.cluster_data', {})
            self.cluster_data()

    def cluster_token(self):
        if not self.db.get('cluster-token'):
            token = self.id_generator()
            self.db.set('cluster-token', token)
            return token
        return self.db.get('cluster-token')

    def id_generator(self, size=6):
        chars = string.ascii_uppercase + string.digits
        return ''.join(random.choice(chars) for _ in range(size))

    def fetch_and_install(self, source, sha):
        unpack = fetch.install_remote(source, 'fetched', sha)

        # Copy the payload into place on the system
        etcd_dir = path('/opt/etcd').makedirs_p(mode=755)
        unpack_dir = path(unpack)
        for d in unpack_dir.dirs():
            d = path(d)
            for f in d.files():
                f.copy(etcd_dir)

        for executable in "etcd", "etcdctl":
            origin = etcd_dir / executable
            target = path('/usr/local/bin/%s' % executable)
            target.exists() and target.remove()
            origin.symlink(target)

    def cluster_string(self, cluster='', proto='http'):
        ''' This method behaves slightly different depending on the
            context of its invocation. If the unit is the leader, the
            connection string should always be built and returned from
            the contents in unit data. Otherwise we should return the
            value set by the leader via leader-data'''
        if is_leader():
            cluster_data = self.cluster_data()
            connection_string = ""
            for u in cluster_data:
                connection_string += ",{}={}://{}:{}".format(u,  # noqa
                                                            proto,
                                                            cluster_data[u]['private_address'],  # noqa
                                                            cluster_data[u]['management_port'])  # noqa
            return connection_string.lstrip(',')
        else:
            return leader_get('cluster')

    def cluster_data(self, unit=None):
        ''' Non duplicating merge of dictionaries. Each new node adds a key to
            the unitdata dict. The dict is the state of the cluster '''

        cluster_data = self.db.get('etcd.cluster_data')

        if not unit:
            unit = {self.unit_name: {'private_address': self.private_address,
                                     'public_address': self.public_address,
                                     'port': self.port,
                                     'management_port': self.management_port,
                                     'unit_name': self.unit_name}
                    }
        # De-dupe the data in the databag
        for k in unit:
            if k not in cluster_data.keys():
                cluster_data.update(unit)
            else:
                # this is potentially destructive
                cluster_data[k] = unit[k]

            self.db.set('etcd.cluster_data', cluster_data)
        return cluster_data
        # Snippet from legacy charm, this greps relation data extracted from
        # charmhelpers to buid the cluster string. It was honestly black magic
        # that mostly worked...
        # if self.hook_data.rels:
        #     # This feels like highway robbery in terms of encapsulation...
        #     cluster_rels = self.hook_data.rels['cluster'][1].keys()
        # introspect the cluster, and form the cluster string.
        # https://github.com/coreos/etcd/blob/master/Documentation/configuration.md#-initial-cluster
        #     reldata = self.hook_data.rels['cluster'][1][cluster_rels[0]]
        #     for unit in reldata:
        #         private = reldata[unit]['private-address']
        #         cluster = '{}{}=http://{}:7001,'.format(cluster,
        #                                            unit.replace('/', ''),
        #                                              private)
        # else:
        #     cluster = "{}=http://{}:{}".format(self.unit_name,
        #                                        self.private_address,
        #                                        self.management_port)

        # return cluster.rstrip(',').lstrip(',')

    def register(self, cluster_data):
        if not self.db.get('registered'):
            command = "etcdctl -C http://{}:{} member add {}" \
                      " http://{}:{}".format(cluster_data['leader_address'],
                                             self.port,
                                             cluster_data['unit_name'],
                                             self.private_address,
                                             self.management_port)
            check_call(split(command))
            self.db.set('registered', True)


def databag_to_dict(databag):
    if not hasattr(databag, 'get_remote'):
        raise ValueError("databag must be a conversation object")

    return {databag.get_remote('unit_name'): {
            'public_address': databag.get_remote('public-address'),
            'private_address': databag.get_remote('private_address'),
            'port': databag.get_remote('port'),
            'unit_name': databag.get_remote('unit_name'),
            'management_port': databag.get_remote('management_port')
            }}
