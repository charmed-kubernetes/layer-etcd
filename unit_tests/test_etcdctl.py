import pytest
import sys
from unittest.mock import MagicMock, patch

charms = MagicMock()
sys.modules['charms'] = charms
ch = MagicMock()
sys.modules['charmhelpers.core.hookenv'] = ch.core.hookenv

from etcdctl import EtcdCtl  # noqa


class TestEtcdCtl:

    @pytest.fixture
    def etcdctl(self):
        return EtcdCtl()

    def test_register(self, etcdctl):
        with patch('etcdctl.EtcdCtl.run') as spcm:
            etcdctl.register({'cluster_address': '127.0.0.1',
                              'unit_name': 'etcd0',
                              'management_port': '1313',
                              'leader_address': 'http://127.1.1.1:1212'})
            spcm.assert_called_with(('etcdctl -C http://127.1.1.1:1212 member '
                                     'add etcd0 https://127.0.0.1:1313'))

    def test_unregister(self, etcdctl):
        with patch('etcdctl.EtcdCtl.run') as spcm:
            etcdctl.unregister('br1212121212')

            spcm.assert_called_with('etcdctl member remove br1212121212')

    def test_member_list(self, etcdctl):
        with patch('etcdctl.EtcdCtl.run') as comock:
            comock.return_value = '7dc8404daa2b8ca0: name=etcd22 peerURLs=https://10.113.96.220:2380 clientURLs=https://10.113.96.220:2379\n'  # noqa
            members = etcdctl.member_list()
            assert(members['etcd22']['unit_id'] == '7dc8404daa2b8ca0')
            assert(members['etcd22']['peer_urls'] == 'https://10.113.96.220:2380')
            assert(members['etcd22']['client_urls'] == 'https://10.113.96.220:2379')

    def test_member_list_with_unstarted_member(self, etcdctl):
        ''' Validate we receive information only about members we can parse
        from the current status string '''
        # 57fa5c39949c138e[unstarted]: peerURLs=http://10.113.96.80:2380
        # bb0f83ebb26386f7: name=etcd9 peerURLs=https://10.113.96.178:2380 clientURLs=https://10.113.96.178:2379
        with patch('etcdctl.EtcdCtl.run') as comock:
            comock.return_value = '57fa5c39949c138e[unstarted]: peerURLs=http://10.113.96.80:2380]\nbb0f83ebb26386f7: name=etcd9 peerURLs=https://10.113.96.178:2380 clientURLs=https://10.113.96.178:2379\n'  # noqa
            members = etcdctl.member_list()
            assert(members['etcd9']['unit_id'] == 'bb0f83ebb26386f7')
            assert(members['etcd9']['peer_urls'] == 'https://10.113.96.178:2380')
            assert(members['etcd9']['client_urls'] == 'https://10.113.96.178:2379')
            assert('unstarted' in members.keys())
            assert(members['unstarted']['unit_id'] == '57fa5c39949c138e')
            assert("10.113.96.80:2380" in members['unstarted']['peer_urls'])

    def test_etcd_v2_version(self, etcdctl):
        ''' Validate that etcdctl can parse versions for both etcd v2 and
        etcd v3 '''
        # Define fixtures of what we expect for the version output
        etcdctl_2_version = "etcdctl version 2.3.8\n"

        with patch('etcdctl.EtcdCtl.run') as comock:
            comock.return_value = etcdctl_2_version
            ver = etcdctl.version()
            assert(ver == '2.3.8')

    def test_etcd_v3_version(self, etcdctl):
        ''' Validate that etcdctl can parse version for etcdctl v3 '''
        etcdctl_3_version = "etcdctl version: 3.0.17\nAPI version: 2\n"
        with patch('etcdctl.EtcdCtl.run') as comock:
            comock.return_value = etcdctl_3_version
            ver = etcdctl.version()
            assert(ver == '3.0.17')
