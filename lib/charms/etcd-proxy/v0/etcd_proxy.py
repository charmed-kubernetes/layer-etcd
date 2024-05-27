"""Library for the etcd-proxy charm.

This library provides the EtcdProxyProvides class, which is used by charms
that provide the etcd-proxy interface. The interface is used to provide
information about the etcd cluster to the proxy charm.

Example usage:

```python
from charms.etcd_proxy.v0.etcd_proxy import EtcdProxyProvides

class MyCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.etcd_proxy = EtcdProxyProvides(self, "etcd-proxy")

    def on_start(self, event):
        self.etcd_proxy.set_client_credentials("key", "cert", "ca")
        self.etcd_proxy.set_cluster_string("cluster_string")
```


"""

import ops
from ops.framework import EventBase, EventSource, Object, ObjectEvents, StoredState
from ops.model import Relation
from typing import Optional
from functools import cached_property
import os

# The unique Charmhub library identifier, never change it
LIBID = "53e4c16b0d5445f9af44f597b3fef518"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

class EtcdAvailable(EventBase):
    """Event emitted when the etcd relation data is available."""

    pass


class EtcdConnected(EventBase):
    """Event emitted when the etcd relation is connected."""

    pass

class EtcdTLSAvailable(EventBase):
    """Event emitted when the etcd relation TLS data is available."""

    pass

class EtcdDisconnected(EventBase):
    """Event emitted when the etcd relation is disconnected."""

    pass

class EtcdConsumerEvents(ObjectEvents):
    """Events emitted by the etcd translation interface."""

    available = EventSource(EtcdAvailable)
    connected = EventSource(EtcdConnected)
    disconnected = EventSource(EtcdDisconnected)
    tls_available = EventSource(EtcdTLSAvailable)

class EtcdProxyRequires(Object):
    state = StoredState()
    on = EtcdConsumerEvents()
    def __init__(self, charm, relation_name, endpoint='etcd-proxy'):
        super().__init__(charm, relation_name)
        self.state.set_default(connected =False, available=False, tls_available=False)
        self.charm = charm
        self.endpoint = endpoint
        self.relation_name = relation_name
        self.framework.observe(charm.on[relation_name].relation_joined, self._joined_or_changed)
        self.framework.observe(charm.on[relation_name].relation_changed, self._joined_or_changed)
        self.framework.observe(charm.on[relation_name].relation_broken, self._broken_or_departed)
        self.framework.observe(charm.on[relation_name].relation_departed, self._broken_or_departed)

    def _joined_or_changed(self):
        self.state.connected = True
        self.on.connected.emit()

        if self.get_cluster_string():
            self.state.available = True
            self.on.available.emit()
            # Get the ca, key, cert from the relation data.
            cert = self.get_client_credentials()
            # The tls state depends on the existence of the ca, key and cert.
            if cert['client_cert'] and cert['client_key'] and cert['client_ca']:  # noqa
                self.state.tls_available = True
                self.on.tls_available.emit()

    def _broken_or_departed(self):
        self.state.connected = False
        self.state.available = False
        self.state.tls_available = False
        self.on.disconnected.emit()

    def get_cluster_string(self):
        ''' Return the connection string, if available, or None. '''
        return self._remote_data.get('cluster')

    def get_client_credentials(self):
        ''' Return a dict with the client certificate, ca and key to
        communicate with etcd using tls. '''
        remote_data = self._remote_data
        return {'client_cert': remote_data.get('client_cert'),
                'client_key': remote_data.get('client_key'),
                'client_ca': remote_data.get('client_ca')}

    def cluster_string(self):
        """
        Get the cluster string, if available, or None.
        """
        return self.get_cluster_string()

    def save_client_credentials(self, key, cert, ca):
        ''' Save all the client certificates for etcd to local files. '''
        self._save_remote_data('client_cert', cert)
        self._save_remote_data('client_key', key)
        self._save_remote_data('client_ca', ca)
    
    @cached_property
    def relation(self) -> Optional[Relation]:
        """Return the relation object for this interface."""
        return self.model.get_relation(self.endpoint)

    @property
    def _remote_data(self):
        """Return the remote relation data for this interface."""
        if not (self.relation and self.relation.units):
            return {}

        first_unit = next(iter(self.relation.units), None)
        data = self.relation.data[first_unit]
        return data

    def _save_remote_data(self, key: str, path: str):
        """Save the remote data to a file."""
        value = self._remote_data.get(key)
        if value:
            parent = os.path.dirname(path)
            if not os.path.isdir(parent):
                os.makedirs(parent)
            with open(path, "w") as stream:
                stream.write(value)



class EtcdProxyProvides(Object):
    state = StoredState()
    def __init__(self, charm, relation_name):
        super().__init__(charm, relation_name)
        self.state.set_default(connected =False)
        self.charm = charm
        self.relation_name = relation_name
        self.framework.observe(charm.on[relation_name].relation_joined, self._joined_or_changed)
        self.framework.observe(charm.on[relation_name].relation_changed, self._joined_or_changed)
        self.framework.observe(charm.on[relation_name].relation_broken, self._broken_or_departed)
        self.framework.observe(charm.on[relation_name].relation_departed, self._broken_or_departed)

    # scope = scopes.GLOBAL #TODO: whats this?

    def _joined_or_changed(self):
        ''' Set state so the unit can identify it is connecting '''
        self.state.connected = True

    def _broken_or_departed(self):
        ''' Set state so the unit can identify it is departing '''
        self.state.connected = False

    def set_client_credentials(self, key, cert, ca):
        ''' Set the client credentials on the global conversation for this
        relation. '''
        relation = self.charm.model.get_relation(self.relation_name)
        if relation:
            relation.data[self.charm.model.unit]["client_key"] = key
            relation.data[self.charm.model.unit]["client_cert"] = cert
            relation.data[self.charm.model.unit]["client_ca"] = ca

    def set_cluster_string(self, cluster_string):
        ''' Set the cluster string on the convsersation '''
        #TODO: is setting this on this unit enough?
        relation = self.charm.model.get_relation(self.relation_name)
        if relation:
            relation.data[self.charm.model.unit]["cluster"] = cluster_string

    # Kept for backwords compatibility
    #TODO: rm this one?
    def provide_cluster_string(self, cluster_string):
        '''
        @params cluster_string - fully formed etcd cluster string.
        This is akin to the --initial-cluster-string setting to the
        etcd-daemon. Proxy's will need to know each declared member of
        the cluster to effectively proxy.
        '''
        relation = self.charm.model.get_relation(self.relation_name)
        if relation:
            relation.data[self.charm.model.unit]["cluster"] = cluster_string
