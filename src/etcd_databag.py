from etcd_lib import get_ingress_address
from etcd_lib import get_bind_address, build_uri
from ops.framework import StoredState

from charm import EtcdCharm
import string
import random
import os


class EtcdDatabag:
    """
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
     'tls_cipher_suites': '',
     'token': '8XG27B',
     'cluster_state': 'existing'}
    """

    def __init__(self, etcd_charm: EtcdCharm):
        self.etcd_charm = etcd_charm
        self.db = StoredState()
        self.build_uri = build_uri
        self.cluster_bind_address = self.get_bind_address("cluster")
        self.port = self.etcd_charm.port
        self.listen_client_urls = [
            build_uri("https", self.get_bind_address("db"), self.port)
        ]
        if self.etcd_charm.config["bind_with_insecure_http"]:
            self.listen_client_urls.insert(0, build_uri("http", "127.0.0.1", 4001))
        self.advertise_urls = [build_uri("https", get_ingress_address("db"), self.port)]
        self.management_port = self.etcd_charm.config["management_port"]
        # Live polled properties
        self.cluster_address = get_ingress_address("cluster")
        self.unit_name = os.getenv("JUJU_UNIT_NAME").replace("/", "")

        # Pull the TLS certificate paths from layer data
        ca_path = self.etcd_charm.ca_certificate_path
        crt_path = self.etcd_charm.server_certificate_path
        key_path = self.etcd_charm.server_key_path

        # Pull the static etcd configuration from layer-data
        self.etcd_conf_dir = self.etcd_charm.etcd_conf_dir
        # This getter determines the current context of the storage path
        # depending on if durable storage is mounted.
        self.etcd_data_dir = self.storage_path()
        self.etcd_daemon = self.etcd_charm.etcd_daemon_process

        self.ca_certificate = ca_path
        self.server_certificate = crt_path
        self.server_key = key_path

        self.tls_cipher_suites = self.etcd_charm.tls_cipher_suites

        # Cluster concerns
        self.cluster = self.db.get("etcd.cluster", "")
        self.token = self.cluster_token()
        self.cluster_state = self.db.get("etcd.cluster-state", "existing")

    def set_cluster(self, value):
        """Set the cluster string for peer registration"""
        self.cluster = value
        self.db.set("etcd.cluster", value)

    def set_cluster_state(self, value):
        """Set the cluster state"""
        self.cluster_state = value
        self.db.set("etcd.cluster-state", value)

    def cluster_token(self):
        """Getter to return the unique cluster token."""
        token = self.etcd_charm.get_peer_data("token")
        if not token and is_leader():
            token = self.id_generator()
            self.etcd_charm.set_peer_data("token", token)
        return token

    def id_generator(self, size=6):
        """Return a random 6 character string for use in cluster init.

        @params size - The size of the string to return in characters
        """
        chars = string.ascii_uppercase + string.digits
        return "".join(random.choice(chars) for _ in range(size))

    def storage_path(self):
        """Storage mounts are limited in snap confinement. Default behavior
        is to version the database files in $SNAP_DATA. However the user can
        attach durable storage, which is mounted in /media. We need a common
        method to determine which storage path we are concerned with"""
        if is_state("data.volume.attached"):
            return "/media/etcd/data"
        else:
            return self.etcd_charm.etcd_data_dir

    def get_bind_address(self, endpoint_name):
        """Returns the address that the service binds to. If the config
        parameter 'bind_to_all_interfaces' is set to true, it returns 0.0.0.0
        If 'bind_to_all_interfaces' is set to false, it returns the
        bind address of the endpoint_name received as parameter

            @param endpoint_name name the endpoint from where the
            bind address is obtained
        """
        if bool(self.etcd_charm.config["bind_to_all_interfaces"]):
            return "0.0.0.0"

        return get_bind_address(endpoint_name)
