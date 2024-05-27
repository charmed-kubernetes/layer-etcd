# Copyright 2023 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Charm library for the etcd reactive relation.

The module defines an interface for a charm that requires the etcd relation.
It encapsulates the functionality and events related to managing the etcd relation,
including connection, availability of data, and handling of TLS credentials.

It uses events to handle state changes in the etcd relation, such as when a connection is
established (`EtcdConnected`), when etcd data is available (`EtcdAvailable`), and when TLS data
for etcd is available (`EtcdTLSAvailable`).

A class `EtcdReactiveRequires` is defined, which provides an abstraction over the charm's
requires relation to etcd. It encapsulates the functionality to check the status of the
relation, get connection details, and handle client credentials.

This module also provides helper methods for handling client credentials, such as
saving them to local files and retrieving them from the relation data.

You can use this charm library in your charm by adding it as a dependency in your
`charmcraft.yaml` file and then importing the relevant classes and functions.

Example usage:
```python
from charms.kubernetes_libs.v0.etcd import EtcdReactiveRequires

...
    def __init__(self, *args):
        self.etcd = EtcdReactiveRequires(self)
        ...
        # Handle the events from the relation
        self.framework.observe(self.etcd.on.connected, self._on_etcd_connected)
        self.framework.observe(self.etcd.on.available, self._on_etcd_available)
        self.framework.observe(self.etcd.on.tls_available, self._on_etcd_tls_available)

```

"""

import hashlib
import json
import logging
import os
from functools import cached_property
from typing import Optional
import ops
from ops.framework import EventBase, EventSource, Object, ObjectEvents, StoredState
from ops.model import Relation

# The unique Charmhub library identifier, never change it
LIBID = "cb9fd1730d05485fbb40e952a585c636"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

log = logging.getLogger(__name__)


class EtcdAvailable(EventBase):
    """Event emitted when the etcd relation data is available."""

    pass


class EtcdConnected(EventBase):
    """Event emitted when the etcd relation is connected."""

    pass

class EtcdPeerConnected(EventBase):
    """Event emitted when the etcd peer relation is connected."""

    pass


class EtcdTLSAvailable(EventBase):
    """Event emitted when the etcd relation TLS data is available."""

    pass

class EtcdDisconnected(EventBase):
    """Event emitted when the etcd relation is disconnected."""

    pass

class EtcdPeerDisconnected(EventBase):
    """Event emitted when the etcd peer relation is disconnected."""

    pass

class EtcdConsumerEvents(ObjectEvents):
    """Events emitted by the etcd translation interface."""

    available = EventSource(EtcdAvailable)
    connected = EventSource(EtcdConnected)
    disconnected = EventSource(EtcdDisconnected)
    tls_available = EventSource(EtcdTLSAvailable)

# TODO: Should this be a seperate event class or not?
class EtcdPeerEvents(ObjectEvents):
    """Events emitted by the etcd translation interface."""

    peer_connected = EventSource(EtcdPeerConnected)
    peer_disconnected = EventSource(EtcdPeerDisconnected)

class EtcdProvides(Object):
    on = EtcdConsumerEvents()
    def __init__(self, charm, relation_name):
        super().__init__(charm, relation_name)
        self.charm = charm
        self.relation_name = relation_name
        self.framework.observe(charm.on[relation_name].relation_joined, self.joined_or_changed)
        self.framework.observe(charm.on[relation_name].relation_changed, self.joined_or_changed)
        self.framework.observe(charm.on[relation_name].relation_broken, self.broken_or_departed)
        self.framework.observe(charm.on[relation_name].relation_departed, self.broken_or_departed)


    def joined_or_changed(self, _):
        ''' Set the connected state from the provides side of the relation. '''
        self.on.connected.emit()

    def broken_or_departed(self, event):
        '''Remove connected state from the provides side of the relation. '''
        len_units = len(event.relation.units)

        if len_units == 1:
            self.on.disconnected.emit()

    def set_client_credentials(self, key, cert, ca):
        ''' Set the client credentials on the charm unit. '''
        relation = self.charm.model.get_relation(self.relation_name)
        if relation:
            relation.data[self.charm.model.unit].update( \
                {"client_key": key, "client_cert": cert, "client_ca": ca})


    def set_connection_string(self, connection_string, version=''):
        ''' Set the connection string on the charm unit. '''
        # Note: Version added as a late-dependency for 2 => 3 migration
        # If no version is specified, consumers should presume etcd 2.x
        relation = self.charm.model.get_relation(self.relation_name)
        if relation:
            relation.data[self.charm.model.unit].update( \
                {"connection_string": connection_string, "version": version})

class EtcdPeers(Object):
    """Peers side of the etcd interface. """
    state = StoredState()
    on = EtcdPeerEvents()
    def __init__(self, charm, relation_name):
        super().__init__(charm, relation_name)
        self.charm = charm
        self.state.set_default(
            joined=False, departing=False
        )
        self.relation_name = relation_name
        self.framework.observe(charm.on[relation_name].relation_joined, self._peer_joined)
        self.framework.observe(charm.on[relation_name].relation_departed, self._peers_going_away)

    def _peer_joined(self):
        """A new peer has joined, emit the peer connected event. """
        self.state.joined = True
        self.on.peer_connected.emit()

    def _peers_going_away(self):
        '''Trigger a state on the unit that it is leaving. We can use this
        state in conjunction with the joined state to determine which unit to
        unregister from the etcd cluster. '''
        self.state.joined = False
        self.state.departing = True
        self.on.peer_disconnected.emit()

    def dismiss(self):
        '''Remove the departing state from all other units in the conversation,
        and we can resume normal operation.
        '''
        #TODO: remove this method? Where do we use this state stuff?
        for peer in self.get_peers():
            unit = self.charm.model.get_unit(peer)
            unit.state.departing = False
        

    def get_peers(self):
        '''Return a list of names for the peers participating in this
        conversation scope. '''
        # TODO: this might be a dict not a list?

        return self.charm.meta.peers.keys()

    def set_db_ingress_address(self, address):
        '''Set the ingress address belonging to the db relation.'''
        relation = self.charm.model.get_relation(self.relation_name) #returns ops.model.Relation
        if relation:
            # ops.Relation.data holds data buckets for each unit in the relation
            relation.data[self.charm.model.unit]["db-ingress-address"] = address

    def get_db_ingress_addresses(self):
        '''Return a list of db ingress addresses'''
        # TODO: Big questionmark
        addresses = []
        relation = self.charm.model.get_relation(self.relation_name)
        for peer in self.get_peers():
            relation.data[peer]['db-ingress-address'] 
            address = peer.get_remote('db-ingress-address')
            if address:
                addresses.append(address)
        return addresses

class EtcdRequires(Object):
    """Requires side of the etcd interface.

    This class is a translation interface that wraps the requires side
    of the reactive etcd interface.
    """

    state = StoredState()
    on = EtcdConsumerEvents()

    def __init__(self, charm, endpoint="etcd"):
        super().__init__(charm, f"relation-{endpoint}")
        self.charm = charm
        self.endpoint = endpoint

        self.state.set_default(
            connected=False, available=False, tls_available=False, connection_string=""
        )

        for event in (
            charm.on[endpoint].relation_created,
            charm.on[endpoint].relation_joined,
            charm.on[endpoint].relation_changed,
            charm.on[endpoint].relation_departed,
            charm.on[endpoint].relation_broken,
        ):
            self.framework.observe(event, self._check_relation)

    def _check_relation(self, _: EventBase):
        """Check if the relation is available and emit the appropriate event."""
        if self.relation:
            self.state.connected = True
            self.on.connected.emit()
            # etcd is available only if the connection string is available
            if self.get_connection_string():
                self.state.available = True
                self.on.available.emit()
                # etcd tls is available only if the tls data is available
                # (i.e. client cert, client key, ca cert)
                cert = self.get_client_credentials()
                if cert["client_cert"] and cert["client_key"] and cert["client_ca"]:
                    self.state.tls_available = True
                    self.on.tls_available.emit()

    def _get_dict_hash(self, data: dict) -> str:
        """Generate a SHA-256 hash for a dictionary.

        This function converts the dictionary into a JSON string, ensuring it
        is sorted in order. It then generates a SHA-256 hash of this string.

        Args:
            data(dict): The dictionary to be hashed.

        Returns:
            str: The hexadecimal representation of the hash of the dictionary.
        """
        dump = json.dumps(data, sort_keys=True)
        hash_obj = hashlib.sha256()
        hash_obj.update(dump.encode())
        return hash_obj.hexdigest()

    @property
    def is_ready(self):
        """Check if the relation is available and emit the appropriate event."""
        if self.relation:
            if self.get_connection_string():
                cert = self.get_client_credentials()
                if all(cert.get(key) for key in ["client_cert", "client_key", "client_ca"]):
                    return True
        return False

    def get_connection_string(self) -> str:
        """Return the connection string for etcd."""
        remote_data = self._remote_data
        if remote_data:
            return remote_data.get("connection_string")
        return ""

    def get_client_credentials(self) -> dict:
        """Return the client credentials for etcd."""
        remote_data = self._remote_data
        return {
            "client_cert": remote_data.get("client_cert"),
            "client_key": remote_data.get("client_key"),
            "client_ca": remote_data.get("client_ca"),
        }

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

    def save_client_credentials(self, ca_path, cert_path, key_path):
        """Save all the client certificates for etcd to local files."""
        credentials = {"client_key": key_path, "client_cert": cert_path, "client_ca": ca_path}
        for key, path in credentials.items():
            self._save_remote_data(key, path)

    def _save_remote_data(self, key: str, path: str):
        """Save the remote data to a file."""
        value = self._remote_data.get(key)
        if value:
            parent = os.path.dirname(path)
            if not os.path.isdir(parent):
                os.makedirs(parent)
            with open(path, "w") as stream:
                stream.write(value)
