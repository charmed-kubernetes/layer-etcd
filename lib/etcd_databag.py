from charmhelpers.core.hookenv import unit_get
from charmhelpers.core.hookenv import config
from charmhelpers.core.hookenv import is_leader
from charmhelpers.core.hookenv import leader_get
from charmhelpers.core import unitdata

import string
import random
import os


class EtcdDatabag:
    '''
    This class represents a configuration object to ease configurtation of an
    etcd unit during deployment and reconfiguration. The full dict of data
    when expanded looks like the following:

    {'public_address': '127.0.0.1',
     'private_address': '127.0.0.1',
     'unit_name': 'etcd0',
     'port': '2380',
     'management_port': '2379',
     'ca_certificate': '/etc/ssl/etcd/ca.pem',
     'server_certificate': '/etc/ssl/etcd/server.pem',
     'server_key': '/etc/ssl/etcd/server-key.pem',
     'token': '8XG27B',
     'cluster_state': 'existing'}
    '''

    def __init__(self):
        self.db = unitdata.kv()
        self.port = config('port')
        self.management_port = config('management_port')
        # Live polled properties
        self.public_address = unit_get('public-address')
        self.private_address = unit_get('private-address')
        self.unit_name = os.getenv('JUJU_UNIT_NAME').replace('/', '')

        # These are hard coded, smell for now.
        self.ca_certificate = "/etc/ssl/etcd/ca.pem"
        self.server_certificate = "/etc/ssl/etcd/server.pem"
        self.server_key = "/etc/ssl/etcd/server-key.pem"
        # Cluster concerns
        self.token = self.cluster_token()
        self.cluster_state = 'existing'

        self.cluster_unit_id = self.db.get('cluster_unit_id')
        self.registration_peer_string = self.db.get('registration_peer_string')

    def cluster_token(self):
        if not is_leader():
            return leader_get('token')

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

    def cache_registration_detail(self, key, val):
        self.db.set(key, val)
