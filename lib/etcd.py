# This entire file needs formatted and abstracted into a class

# In the older etcd charm there is 2 definite sets of data structures being
# used. This is an attempt to simplify to just:
#
# {etcd1: {
#         'public_address': 127.0.0.1,
#         'private_address': 127.0.0.1,
#         'unit_name': etcd1)
#         }}

from charmhelpers.core.hookenv import unit_get
from charmhelpers.core.hookenv import is_leader
from charmhelpers.core.hookenv import leader_get
from charmhelpers.core.hookenv import config
from charmhelpers.core.hookenv import log

from charmhelpers.core import unitdata
from charmhelpers import fetch
from os import getenv
from path import path
import random
from shlex import split
import string
from subprocess import check_call
from subprocess import CalledProcessError


class EtcdHelper:

    def __init__(self):
        self.db = unitdata.kv()
        self.public_address = unit_get('public-address')
        self.private_address = unit_get('private-address')
        self.hook_data = unitdata.HookData()
        self.unit_name = getenv('JUJU_UNIT_NAME').replace('/', '')
        self.port = config('port')
        self.management_port = config('management_port')
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
        ''' Return a random 6 character string for use in cluster init.

            @params size - The size of the string to return in characters
        '''
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

    def cluster_string(self, proto='http', internal=True):
        ''' This method behaves slightly different depending on the
            context of its invocation. If the unit is the leader, the
            connection string should always be built and returned from
            the contents in unit data. Otherwise we should return the
            value set by the leader via leader-data

            @params proto - Determines the output prefix depending on need. eg:
                           http://127.0.0.1:4001 or etcd://127.0.0.1:4001
            @params internal - Boolean value to determine if management or
                               client cluster string is required.
        '''
        if is_leader():
            cluster_data = self.cluster_data()
            connection_string = ""
            if internal:
                for u in cluster_data:
                    connection_string += ",{}={}://{}:{}".format(u,  # noqa
                                                                 proto,
                                                                 cluster_data[u]['private_address'],  # noqa
                                                                 self.management_port)  # noqa
            else:
                for u in cluster_data:
                    connection_string += ",{}://{}:{}".format(proto,
                                                              cluster_data[u]['private_address'],  # noqa
                                                              self.port)
            return connection_string.lstrip(',')
        else:
            return leader_get('cluster')

    def cluster_data(self, unit=None):
        ''' Non duplicating merge of dictionaries. Each new node adds a key to
            the unitdata dict. The dict is the persisted state of the cluster
            to be used if the leader "goes away". Its the only liferaft in the
            event of an emergency.
        '''
        # ...I'm only mostly certain of this

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
            cluster_data[k] = unit[k]
        self.db.set('etcd.cluster_data', cluster_data)
        return cluster_data

    def register(self, cluster_data):
        ''' Perform self registration against the Etcd leader.

            @params cluster_data - a dict of the data to pass to the
            etcd leader unit to declare the units intent to join the cluster.
        '''
        if not self.db.get('registered'):
            command = "etcdctl -C http://{}:{} member add {}" \
                      " http://{}:{}".format(cluster_data['leader_address'],
                                             self.port,
                                             cluster_data['unit_name'],
                                             self.private_address,
                                             self.management_port)
            try:
                check_call(split(command))
                self.db.set('registered', True)
            except CalledProcessError:
                log('Notice: Unit failed to registration command', 'WARNING')

    def unregister(self, cluster_data):
        # this wont work, it needs to be etcdctl member remove {{GUID}}
        command = "etcdctl -C http://{}:{} member remove {}" \
                  " http://{}:{}".format(cluster_data['leader_address'],
                                         config('port'),
                                         cluster_data['private_address'],
                                         config('management_port'))
        check_call(split(command))


def remove_unit_from_cache(self, unit_name):
    ''' Cache data is built with the UNIT_NAME as the key holding
        the units data. We can expire their cache entry with just
        the unit name.

        @param - unit_name - the unit name# eg: etcd1
    '''
    cluster_data = self.db.get('etcd.cluster_data')
    cluster_data.pop(unit_name, None)
    # update with the removed unit
    self.db.set('etcd.cluster_data', cluster_data)
    return cluster_data
