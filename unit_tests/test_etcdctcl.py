import pytest

from etcdctl import EtcdCtl
from mock import patch


class TestEtcdCtl:

    @pytest.fixture
    def etcdctl(self):
        return EtcdCtl()

    def test_register(self):
        with patch('etcdctl.check_output') as spcm:
            self.etcdctl().register({'private_address': '127.0.0.1',
                                     'port': '1212',
                                     'unit_name': 'etcd0',
                                     'management_port': '1313',
                                     'leader_address': '127.1.1.1'})
            spcm.assert_called_with(['etcdctl',
                                     '-C',
                                     'http://127.1.1.1:1212',
                                     'member',
                                     'add',
                                     'etcd0',
                                     'http://127.0.0.1:1313'])  # noqa

    def test_unregister(self):
        with patch('etcdctl.check_output') as spcm:
            self.etcdctl().unregister({'leader_address': '127.1.1.1',
                                       'port': '1212',
                                       'unit_id': 'br1212121212'})

            spcm.assert_called_with(['etcdctl',
                                     '-C',
                                     'http://127.1.1.1:1212',
                                     'member',
                                     'remove',
                                     'br1212121212'])

    def test_member_list(self):
        with patch('etcdctl.check_output') as comock:
            comock.return_value = b'7dc8404daa2b8ca0: name=etcd22 peerURLs=https://10.113.96.220:2380 clientURLs=https://10.113.96.220:2379\n'  # noqa
            members = self.etcdctl().member_list()
            assert(members['etcd22']['unit_id'] == '7dc8404daa2b8ca0')
            assert(members['etcd22']['peer_urls'] == 'https://10.113.96.220:2380')  # noqa
            assert(members['etcd22']['client_urls'] == 'https://10.113.96.220:2379')  # noqa

    def test_cluster_health_unhealthy(self):
        with patch('etcdctl.check_output') as comock:
            comock.return_value = b''

    def test_cluster_health_healthy(self):
        pass
