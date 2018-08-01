from charms import layer
from charmhelpers.core.hookenv import unit_get
from charmhelpers.core.hookenv import config
from charmhelpers.core.hookenv import is_leader
from charmhelpers.core.hookenv import leader_get
from charmhelpers.core import unitdata
from charms.reactive import is_state
from etcd_lib import get_ingress_address

import string
import random
import os


class EtcdDatabag:
    '''
    This class represents a configuration object to ease configuration of an
    etcd unit during deployment and reconfiguration. The full dict of data
    when expanded looks like the following:

    {'public_address': '127.0.0.1',
     'cluster_address': '127.0.0.1',
     'db_address': '127.0.0.1',
     'unit_name': 'etcd0',
     'port': '2380',
     'management_port': '2379',
     'ca_certificate': '/etc/ssl/etcd/ca.crt',
     'server_certificate': '/etc/ssl/etcd/server.crt',
     'server_key': '/etc/ssl/etcd/server.key',
     'token': '8XG27B',
     'cluster_state': 'existing'}
    '''

    def __init__(self):
        self.db = unitdata.kv()
        self.port = config('port')
        self.management_port = config('management_port')
        # Live polled properties
        self.public_address = unit_get('public-address')
        self.cluster_address = get_ingress_address('cluster')
        self.db_address = get_ingress_address('db')
        self.unit_name = os.getenv('JUJU_UNIT_NAME').replace('/', '')

        # Pull the TLS certificate paths from layer data
        tls_opts = layer.options('tls-client')
        ca_path = tls_opts['ca_certificate_path']
        crt_path = tls_opts['server_certificate_path']
        key_path = tls_opts['server_key_path']

        # Pull the static etcd configuration from layer-data
        etcd_opts = layer.options('etcd')
        self.etcd_conf_dir = etcd_opts['etcd_conf_dir']
        # This getter determines the current context of the storage path
        # depending on if durable storage is mounted.
        self.etcd_data_dir = self.storage_path()
        self.etcd_daemon = etcd_opts['etcd_daemon_process']

        self.ca_certificate = ca_path
        self.server_certificate = crt_path
        self.server_key = key_path

        # Cluster concerns
        self.token = self.cluster_token()
        self.cluster_state = 'existing'

    def cluster_token(self):
        ''' Getter to return the unique cluster token. '''
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

    def storage_path(self):
        ''' Storage mounts are limited in snap confinement. Default behavior
        is to version the database files in $SNAP_DATA. However the user can
        attach durable storage, which is mounted in /media. We need a common
        method to determine which storage path we are concerned with '''

        etcd_opts = layer.options('etcd')

        if is_state('data.volume.attached'):
            return "/media/etcd/data"
        else:
            return etcd_opts['etcd_data_dir']
