#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.

"""Charm the service"""

import logging
import ops 
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus, MaintenanceStatus
from ops.framework import StoredState


log = logging.getLogger(__name__)

VALID_LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

class EtcdCharm(ops.CharmBase):
    """Charm the service."""

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        # Observe charm events
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.stop, self._on_stop)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on.upgrade_charm, self._on_upgrade_charm)

        # Observe certificate events
        self.framework.observe(self.on.certificates_relation_joined, self._on_certificates_relation_joined)
        self.framework.observe(self.on.certificates_relation_created, self._on_certificates_relation_created)
        self.framework.observe(self.on.certificates_relation_changed, self._on_certificates_relation_changed)
        self.framework.observe(self.on.certificates_relation_broken, self._on_certificates_relation_broken)
        self.framework.observe(self.on.certificates_relation_departed, self._on_certificates_relation_departed)

        # Observe cluster events
        self.framework.observe(self.on.cluster_relation_joined, self._on_cluster_relation_joined)
        self.framework.observe(self.on.cluster_relation_created, self._on_cluster_relation_created)
        self.framework.observe(self.on.cluster_relation_changed, self._on_cluster_relation_changed)
        self.framework.observe(self.on.cluster_relation_broken, self._on_cluster_relation_broken)
        self.framework.observe(self.on.cluster_relation_departed, self._on_cluster_relation_departed)

        # Observe db events
        self.framework.observe(self.on.db_relation_joined, self._on_db_relation_joined)
        self.framework.observe(self.on.db_relation_created, self._on_db_relation_created)
        self.framework.observe(self.on.db_relation_changed, self._on_db_relation_changed)
        self.framework.observe(self.on.db_relation_broken, self._on_db_relation_broken)
        self.framework.observe(self.on.db_relation_departed, self._on_db_relation_departed)

        # hook template?

        # leader settings
        self.framework.observe(self.on.leader_elected, self._on_leader_elected)
        self.framework.observe(self.on.leader_settings_changed, self._on_leader_settings_changed)

        # post & pre -series upgrade
        self.framework.observe(self.on.post_series_upgrade, self._on_post_series_upgrade)
        self.framework.observe(self.on.pre_series_upgrade, self._on_pre_series_upgrade)

        # proxy events
        self.framework.observe(self.on.proxy_relation_joined, self._on_proxy_relation_joined)
        self.framework.observe(self.on.proxy_relation_created, self._on_proxy_relation_created)
        self.framework.observe(self.on.proxy_relation_changed, self._on_proxy_relation_changed)
        self.framework.observe(self.on.proxy_relation_broken, self._on_proxy_relation_broken)
        self.framework.observe(self.on.proxy_relation_departed, self._on_proxy_relation_departed)

        # relation events
        self.framework.observe(self.on.config_changed, self._on_config_changed)

    def _on_pre_series_upgrade(self, event):
        pass

    def _on_leader_settings_changed(self, event):
        """The leader executes the runtime configuration update for the cluster,
        as it is the controlling unit. Will render config, close and open ports and
        restart the etcd service."""        
        log.info('Leader settings changed')
        self.model.unit.status = ops.model.ActiveStatus('Leader settings changed')



    def _on_install(self, event):
        log.info('Installing Etcd')
        self.model.unit.status = ops.model.BlockedStatus('Waiting for Etcd to start')


    def _on_start(self, event):
        log.info('Starting Etcd')
        self.model.unit.status = ops.model.ActiveStatus('Etcd is running')

    def _on_stop(self, event):
        log.info('Stopping Etcd')
        self.model.unit.status = ops.model.BlockedStatus('Etcd is stopped')
    
    def _on_config_changed(self, event):
        log.info('Configuring Etcd')
        self.model.unit.status = ops.model.WaitingStatus('Etcd is being configured')

        # switch all config options charm doesn't know which config changed
        if self.config



if __name__ == "__main__":
    ops.main(EtcdCharm)