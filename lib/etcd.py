# This entire file needs formatted and abstracted into a class

# In the older etcd charm there is 2 definite sets of data structures being
# used.
#
# cluster_data = {
#    'unit_name': os.environ['JUJU_UNIT_NAME'].replace('/', ''),
#    'private_address': unit_get('private_address'),
#    'public_address': unit_get('public_address'),
#    'cluster_state': 'new'
# }
#

from charmhelpers.core.hookenv import unit_get
from charmhelpers.core.hookenv import is_leader
from charmhelpers.core import unitdata
from charmhelpers import fetch
from os import getenv
from path import path
import random
from shlex import split
import string
from subprocess import check_call


class EtcdHelper:

    def __init__(self):
        self.db = unitdata.kv()
        self.public_address = unit_get('public-address')
        self.private_address = unit_get('private-address')
        self.hook_data = unitdata.HookData()
        self.unit_name = getenv('JUJU_UNIT_NAME').replace('/', '')

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

    def cluster_string(self, cluster=''):
        if not is_leader():
            cluster = "{},{}=http://{}:7001".format(cluster,
                                                    self.unit_name,
                                                    self.private_address)
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
        else:
            cluster = "{}=http://{}:7001".format(self.unit_name,
                                                 self.private_address)

        return cluster.rstrip(',').lstrip(',')

    def register(self, cluster_data):
        if not self.db.get('registered'):
            command = "etcdctl -C http://{}:4001 member add {}" \
                      " http://{}:7001".format(cluster_data['leader_address'],
                                               cluster_data['unit_name'],
                                               self.private_address)
            check_call(split(command))
            self.db.set('registered', True)
