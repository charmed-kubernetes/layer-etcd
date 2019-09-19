from charms import layer
from charmhelpers.core.hookenv import unit_get
from charmhelpers.core.hookenv import config
from charmhelpers.core.hookenv import is_leader
from charmhelpers.core.hookenv import leader_get, leader_set
from charmhelpers.core import unitdata
from charms.reactive import is_state
from etcd_lib import get_ingress_address
from etcd_lib import get_bind_address

import string
import random
import os


class EtcdDatabag:
    '''
    This class represents a configuration object to ease configuration of an
    etcd unit during deployment and reconfiguration. The full dict of data
    when expanded looks like the following:

    {'public_address': '127.0.0.1',
     'cluster_bind_address': '127.0.0.1',
     'db_bind_address': '127.0.0.1',
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
        self.cluster_bind_address = self.get_bind_address('cluster')
        self.db_bind_address = self.get_bind_address('db')
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
        token = leader_get('token')
        if not token and is_leader():
            token = self.id_generator()
            leader_set({'cluster-token': token})
        return token

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

    def get_bind_address(self, endpoint_name):
        ''' Returns the address that the service binds to. If the config
        parameter 'bind_to_all_interfaces' is set to true, it returns 0.0.0.0
        If 'bind_to_all_interfaces' is set to false, it returns the
        bind address of the endpoint_name received as parameter

            @param endpoint_name name the endpoint from where the
            bind address is obtained
        '''
        if bool(config('bind_to_all_interfaces')):
            return '0.0.0.0'

        return get_bind_address(endpoint_name)
