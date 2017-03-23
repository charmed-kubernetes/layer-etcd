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
                                     'leader_address': 'http://127.1.1.1:1212'})  # noqa
            spcm.assert_called_with(['/snap/bin/etcd.etcdctl',
                                     '-C',
                                     'http://127.1.1.1:1212',
                                     'member',
                                     'add',
                                     'etcd0',
                                     'https://127.0.0.1:1313'])  # noqa

    def test_unregister(self):
        with patch('etcdctl.check_output') as spcm:
            self.etcdctl().unregister('br1212121212')

            spcm.assert_called_with(['/snap/bin/etcd.etcdctl',
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
        ''' Validate we receive information only about members we can parse
        from the current status string '''
        # 57fa5c39949c138e[unstarted]: peerURLs=http://10.113.96.80:2380
        # bb0f83ebb26386f7: name=etcd9 peerURLs=https://10.113.96.178:2380 clientURLs=https://10.113.96.178:2379  # noqa
        with patch('etcdctl.check_output') as comock:
            comock.return_value = b'57fa5c39949c138e[unstarted]: peerURLs=http://10.113.96.80:2380]\nbb0f83ebb26386f7: name=etcd9 peerURLs=https://10.113.96.178:2380 clientURLs=https://10.113.96.178:2379\n'  # noqa
            members = self.etcdctl().member_list()
            assert(members['etcd9']['unit_id'] == 'bb0f83ebb26386f7')
            assert(members['etcd9']['peer_urls'] == 'https://10.113.96.178:2380')  # noqa
            assert(members['etcd9']['client_urls'] == 'https://10.113.96.178:2379')  # noqa
            assert('unstarted' in members.keys())
            assert(members['unstarted'] == {})

    def test_etcd_v2_version(self):
        ''' Validate that etcdctl can parse versions for both etcd v2 and
        etcd v3 '''
        # Define fixtures of what we expect for the version output
        etcdctl_2_version = b"etcdctl version 2.3.8\n"

        with patch('etcdctl.check_output') as comock:
            comock.return_value = etcdctl_2_version
            ver = self.etcdctl().version()
            assert(ver == '2.3.8')

    def test_etcd_v3_version(self):
        ''' Validate that etcdctl can parse version for etcdctl v3 '''
        etcdctl_3_version = b"etcdctl version: 3.0.17\nAPI version: 2\n"
        with patch('etcdctl.check_output') as comock:
            comock.return_value = etcdctl_3_version
            ver = self.etcdctl().version()
            assert(ver == '3.0.17')
