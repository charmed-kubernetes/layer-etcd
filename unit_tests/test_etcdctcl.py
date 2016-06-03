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
                                     'unit_name': 'etcd0',
                                     'management_port': '1313',
                                     'leader_address': 'http://127.1.1.1:1212'})
            spcm.assert_called_with(['etcdctl',
                                     '-C',
                                     'http://127.1.1.1:1212',
                                     'member',
                                     'add',
                                     'etcd0',
                                     'http://127.0.0.1:1313'])  # noqa

    def test_unregister(self):
        with patch('etcdctl.check_output') as spcm:
            self.etcdctl().unregister('br1212121212')

            spcm.assert_called_with(['etcdctl',
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

    def test_member_list_with_unstarted_member(self):
        # 57fa5c39949c138e[unstarted]: peerURLs=http://10.113.96.80:2380
        # bb0f83ebb26386f7: name=etcd9 peerURLs=https://10.113.96.178:2380 clientURLs=https://10.113.96.178:2379
        pass
