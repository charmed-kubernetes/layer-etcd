import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4

from etcdctl import (
    EtcdCtl,
    etcdctl_command,
    get_connection_string,
)  # noqa

from reactive.etcd import (
    host,
    pre_series_upgrade,
    post_series_upgrade,
    status,
    update_relation,
)


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
            spcm.assert_called_with('member add etcd0 https://127.0.0.1:1313', api=2, endpoints='http://127.1.1.1:1212')

    def test_unregister(self, etcdctl):
        with patch('etcdctl.EtcdCtl.run') as spcm:
            etcdctl.unregister('br1212121212')

            spcm.assert_called_with(['member', 'remove', 'br1212121212'], api=2, endpoints=None)

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
        etcdctl_2_version = b"etcdctl version 2.3.8\n"
        with patch('etcdctl.check_output') as comock:
            comock.return_value = etcdctl_2_version
            ver = etcdctl.version()
            assert(ver == '2.3.8')

    def test_etcd_v3_version(self, etcdctl):
        ''' Validate that etcdctl can parse version for etcdctl v3 '''
        etcdctl_3_version = b"etcdctl version: 3.0.17\nAPI version: 2\n"
        with patch('etcdctl.check_output') as comock:
            comock.return_value = etcdctl_3_version
            ver = etcdctl.version()
            assert(ver == '3.0.17')

    def test_etcdctl_command(self):
        ''' Validate sane results from etcdctl_command '''
        assert(isinstance(etcdctl_command(), str))

    def test_etcdctl_environment_with_version_2(self, etcdctl):
        ''' Validate that environment gets set correctly
        spoiler alert; it shouldn't be set when passing --version '''
        with patch('etcdctl.check_output') as comock:
            etcdctl.run('member list', api=2)
            api_version = comock.call_args[1].get('env').get('ETCDCTL_API')
            assert(api_version == '2')

    def test_etcdctl_environment_with_version_3(self, etcdctl):
        ''' Validate that environment gets set correctly
        spoiler alert; it shouldn't be set when passing --version '''
        with patch('etcdctl.check_output') as comock:
            etcdctl.run('member list', api=3)
            api_version = comock.call_args[1].get('env').get('ETCDCTL_API')
            assert(api_version == '3')

    def test_get_connection_string(self):
        ''' Validate the get_connection_string function
        gives a sane return.
        '''
        assert(
            get_connection_string(['1.1.1.1'], '1111') ==
            'https://1.1.1.1:1111'
        )

    def test_series_upgrade(self):
        assert host.service_pause.call_count == 0
        assert host.service_resume.call_count == 0
        assert status.blocked.call_count == 0
        pre_series_upgrade()
        assert host.service_pause.call_count == 1
        assert host.service_resume.call_count == 0
        assert status.blocked.call_count == 1
        post_series_upgrade()
        assert host.service_pause.call_count == 1
        assert host.service_resume.call_count == 1
        assert status.blocked.call_count == 1

    @patch('reactive.etcd.force_rejoin')
    @patch('reactive.etcd.unitdata.kv')
    @patch('reactive.etcd.hookenv.relation_get')
    def test_rejoin_trigger(self, relation_get_mock, kv_mock,
                            rejoin_mock):
        """Test that unit will trigger `force_rejoin` on new request"""
        local_storage_mock = MagicMock()
        kv_mock.return_value = local_storage_mock

        old_request_id = uuid4().hex
        new_request_id = uuid4().hex
        local_storage_mock.get.return_value = old_request_id
        relation_get_mock.return_value = new_request_id

        update_relation()
        local_storage_mock.set.assert_called_with('force_rejoin', new_request_id)
        rejoin_mock.assert_called_once()

    @patch('reactive.etcd.force_rejoin')
    @patch('reactive.etcd.unitdata.kv')
    @patch('reactive.etcd.hookenv.relation_get')
    def test_dont_rejoin_on_same_request(self, relation_get_mock, kv_mock,
                                         rejoin_mock):
        """Test that unit wont try to `force_rejoin` without new request"""
        local_storage_mock = MagicMock()
        kv_mock.return_value = local_storage_mock

        request_id = uuid4()

        local_storage_mock.get.return_value = request_id
        relation_get_mock.return_value = request_id

        update_relation()

        rejoin_mock.assert_not_called()

    @patch('reactive.etcd.force_rejoin')
    @patch('reactive.etcd.hookenv.relation_get')
    def test_dont_rejoin_on_no_request(self, relation_get_mock, rejoin_mock):
        """Test that unit wont try to `force_rejoin` if there's no request"""

        relation_get_mock.return_value = None

        update_relation()

        rejoin_mock.assert_not_called()
