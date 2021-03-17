import pytest
from unittest.mock import patch, mock_open, MagicMock

import reactive.etcd

from etcdctl import (
    EtcdCtl,
    etcdctl_command,
    get_connection_string,
)  # noqa

from reactive.etcd import (
    config,
    endpoint_from_flag,
    GRAFANA_DASHBOARD_NAME,
    hookenv,
    host,
    log,
    pre_series_upgrade,
    post_series_upgrade,
    resource_get,
    register_grafana_dashboard,
    register_prometheus_jobs,
    render_grafana_dashboard,
    status,
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

    def test_render_grafana_dashboard(self):
        """Test loading of Grafana dashboard."""
        datasource = 'prometheus'
        config.return_value = datasource
        hookenv.charm_dir.return_value = './'
        raw_template = b'{"panels": [{"datasource": "<< datasource >>"}]}'
        expected_dashboard = {
            'panels': [
                {'datasource': '{} - Juju generated source'.format(datasource)}
            ]}

        with patch('builtins.open', mock_open(read_data=raw_template)):
            rendered_dashboard = render_grafana_dashboard()

        assert rendered_dashboard == expected_dashboard

    @patch('reactive.etcd.render_grafana_dashboard')
    @patch('reactive.etcd.set_flag')
    def test_register_grafana_dashboard(self, set_flag_mock,
                                        mock_dashboard_render):
        """Register grafana dashboard."""
        dashboard_file = '/foo/bar'
        dashboard_json = {'foo': 'bar'}
        resource_get.return_value = dashboard_file
        mock_dashboard_render.return_value = dashboard_json
        grafana = MagicMock()
        endpoint_from_flag.return_value = grafana

        register_grafana_dashboard()

        mock_dashboard_render.assert_called_once()
        grafana.register_dashboard.assert_called_with(
            name=GRAFANA_DASHBOARD_NAME, dashboard=dashboard_json)
        set_flag_mock.assert_called_with('grafana.configured')

    @patch('reactive.etcd.set_flag')
    def test_register_grafana_dashboard_missing_resource(self, set_flag_mock):
        """Log error if 'dashboard' resource is missing."""
        resource_get.return_value = None
        grafana = MagicMock()
        endpoint_from_flag.return_value = grafana
        expected_err = "Failed to register Grafana dashboard. Resource " \
                       "'dashboard' is missing."

        register_grafana_dashboard()

        log.assert_called_with(expected_err, level=hookenv.ERROR)
        grafana.register_dashboard.assert_not_called()
        set_flag_mock.assert_not_called()

    def test_register_prometheus_job(self, mocker):
        """Test successful registration of prometheus job."""
        ingress_address = '10.0.0.1'
        port = '2379'
        targets = ['{}:{}'.format(ingress_address, port)]
        prometheus_mock = MagicMock()
        etcd_cluster_mock = MagicMock()
        job_data = {'scheme': 'https',
                    'static_configs': [{'targets': targets}]
                    }

        etcd_cluster_mock.get_db_ingress_addresses.return_value = []
        endpoint_from_flag.side_effect = [prometheus_mock, etcd_cluster_mock]
        mocker.patch.object(reactive.etcd, 'etcd_reachable_from_endpoint',
                            return_value=True)
        mocker.patch.object(reactive.etcd, 'get_ingress_address',
                            return_value=ingress_address)
        reactive.etcd.config.return_value = port

        register_prometheus_jobs()

        prometheus_mock.register_job.assert_called_with(job_name='etcd',
                                                        job_data=job_data)
        reactive.etcd.set_flag.assert_called_with('prometheus.configured')

    def test_register_prometheus_job_endpoint_unreachable(self, mocker):
        """Test that registration doesn't occur if prometheus cant reach etcd"""
        prometheus_mock = MagicMock()
        etcd_cluster_mock = MagicMock()
        endpoint_from_flag.side_effect = [prometheus_mock, etcd_cluster_mock]
        mocker.patch.object(reactive.etcd, 'etcd_reachable_from_endpoint',
                            return_value=False)

        register_prometheus_jobs()

        log.assert_called_with('Aborting Prometheus metrics collection. Etcd '
                               'is not reachable by prometheus client',
                               hookenv.WARNING)
        prometheus_mock.register_job.assert_not_called()

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
