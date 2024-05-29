#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.

"""Charm the service"""

import logging
import ops 
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus, MaintenanceStatus
from ops.framework import StoredState

from charms.operator_libs_linux.v2.snap import Snap, add, remove, SnapError
from charms.etcd.v0.etcd import EtcdProvides
from charms.etcd_proxy.v0.etcd import EtcdProxyProvides
from ops.interface_tls_certificates import CertificatesRequires

log = logging.getLogger(__name__)

VALID_LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
ETCD_SNAP_NAME = 'etcd'
class EtcdCharm(ops.CharmBase):
    """Charm the service."""

    state = StoredState()
    etcd_conf_dir = "/var/snap/etcd/common" #Path to render etcd configuration
    etcd_data_dir = "/var/snap/etcd/current" #Path to presume for etcd data_persistence
    etcd_daemon_process = "snap.etcd.etcd" #Process to target for etcd daemon restarts

    # TLS client and server cert paths
    ca_certificate_path= "/var/snap/etcd/common/ca.crt"
    server_certificate_path= "/var/snap/etcd/common/server.crt"
    server_key_path= "/var/snap/etcd/common/server.key"
    client_certificate_path= "/var/snap/etcd/common/client.crt"
    client_key_path= "/var/snap/etcd/common/client.key"
   
    # cdk-service-kicker TODO: where do I need this?
    services = ["snap.etcd.etcd"]

    # etcd ports TODO


    def __init__(self, *args):

        super().__init__(*args)
        self.snap = None
        self.state.set_default(snap_started=False)

        # etcd charm integrations
        self.certificates = CertificatesRequires(self, 'certificates')
        # self.etcd = EtcdProvides(self, 'etcd')
        # self.etcd_proxy = EtcdProxyProvides(self, 'etcd-proxy')

        # Observe charm events
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.stop, self._on_stop)
        # self.framework.observe(self.on.update_status, self._on_update_status)
        # self.framework.observe(self.on.upgrade_charm, self._on_upgrade_charm)

        # # Observe certificate events
        # self.framework.observe(self.on.certificates_relation_joined, self._on_certificates_relation_joined)
        # self.framework.observe(self.on.certificates_relation_created, self._on_certificates_relation_created)
        # self.framework.observe(self.on.certificates_relation_changed, self._on_certificates_relation_changed)
        # self.framework.observe(self.on.certificates_relation_broken, self._on_certificates_relation_broken)
        # self.framework.observe(self.on.certificates_relation_departed, self._on_certificates_relation_departed)

        # # Observe cluster events
        # self.framework.observe(self.on.cluster_relation_joined, self._on_cluster_relation_joined)
        # self.framework.observe(self.on.cluster_relation_created, self._on_cluster_relation_created)
        # self.framework.observe(self.on.cluster_relation_changed, self._on_cluster_relation_changed)
        # self.framework.observe(self.on.cluster_relation_broken, self._on_cluster_relation_broken)
        # self.framework.observe(self.on.cluster_relation_departed, self._on_cluster_relation_departed)

        # # Observe db events
        # self.framework.observe(self.on.db_relation_joined, self._on_db_relation_joined)
        # self.framework.observe(self.on.db_relation_created, self._on_db_relation_created)
        # self.framework.observe(self.on.db_relation_changed, self._on_db_relation_changed)
        # self.framework.observe(self.on.db_relation_broken, self._on_db_relation_broken)
        # self.framework.observe(self.on.db_relation_departed, self._on_db_relation_departed)

        # hook template?

        # # leader settings
        # self.framework.observe(self.on.leader_elected, self._on_leader_elected)
        # self.framework.observe(self.on.leader_settings_changed, self._on_leader_settings_changed)

        # # post & pre -series upgrade
        # self.framework.observe(self.on.post_series_upgrade, self._on_post_series_upgrade)
        # self.framework.observe(self.on.pre_series_upgrade, self._on_pre_series_upgrade)

        # proxy events
        # self.framework.observe(self.on.proxy_relation_joined, self._on_proxy_relation_joined)
        # self.framework.observe(self.on.proxy_relation_created, self._on_proxy_relation_created)
        # self.framework.observe(self.on.proxy_relation_changed, self._on_proxy_relation_changed)
        # self.framework.observe(self.on.proxy_relation_broken, self._on_proxy_relation_broken)
        # self.framework.observe(self.on.proxy_relation_departed, self._on_proxy_relation_departed)

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


    def _get_target_etcd_channel(self):
        """
        Check whether or not etcd is already installed. i.e. we're
        going through an upgrade.  If so, leave the etcd version alone,
        if we're a new install, we can set the default channel here.

        If the user has specified a version, then just return that.

        :return: String snap channel
        """
        channel = self.model.config['channel']
        if channel == "auto":
            if self.is_etcd_installed():
                return False
            else:
                return "3.4/stable"
        else:
            return channel

    def is_etcd_installed(self):
        """Check if a snap is installed"""
        if self.snap != None:
            return self.snap.present
        log.info('Etcd snap is not installed')
        return False
    
    def _on_install(self, event):
        """Install the etcd snap if it is not already installed or if the channel has changed."""
        if not self.is_etcd_installed():
            log.info('Installing Etcd')
            self.model.unit.status = ops.model.BlockedStatus('Waiting for Etcd to start')
        try:
            #TODO: check if this also does a refresh if we only change the channel
            self.snap = add(snap_names ='etcd', \
                channel=self._get_target_etcd_channel(), \
                    )
            self.snap.start() #TODO:do i need this?
            self.state.snap_started = True
            log.info('Installed Etcd Snap: %s', str(self.snap))
        except SnapError as e:
            log.error(f"Could not install etcd: {e}")
            self.model.unit.status = ops.model.BlockedStatus('Etcd installation failed')
            return
    
    def reconfigure_snap(self, _):
        """Reconfigure the snap with the new configuration options"""
        if self.is_etcd_installed() and self._has_channel_changed():
            self.snap.ensure(channel=self._get_target_etcd_channel(), snap_names='etcd', classic=True) #TODO: check if I also need to pass snapstate
            self.snap.restart()
            self.state.snap_started = True
            self.model.unit.status = ops.model.ActiveStatus('Etcd is running')
            return
        


    def _on_start(self, _):
        log.info('Starting Etcd')
        return
        
        self.model.unit.status = ops.model.ActiveStatus('Etcd is running')

    def _on_stop(self, _):
        log.info('Stopping Etcd')
        if self.is_etcd_installed():
            self.snap.stop()
            self.state.snap_started = False
            self.model.unit.status = ops.model.BlockedStatus('Etcd is stopped')
    
    def _has_channel_changed(self):
        """Check if the snap channel has changed"""
        if self.config['channel'] != self.snap.channel:
            return True
        return False

    
    def _on_config_changed(self, event):
        log.info('Configuring Etcd')
        self.model.unit.status = ops.model.WaitingStatus('Etcd is being configured')
        
        #channel changed, reconfigure snap
        self.reconfigure_snap(event)

        #port changed
       


if __name__ == "__main__":
    ops.main(EtcdCharm)
