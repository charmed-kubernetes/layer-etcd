import pytest

from pytest import param
from unittest.mock import patch, mock_open
from netaddr import IPAddress, IPNetwork

from charmhelpers.core import hookenv

import etcd_lib

from etcd_lib import (
    etcd_reachable_from_endpoint,
    render_grafana_dashboard,
)


@pytest.mark.parametrize('bind_all, ingress_addr, endpoint_net, expected', [
    param(True, None, [], True, id='service-bound-on-all-interfaces'),
    param(False, None, [], False, id='no-endpoint-addr'),
    param(False, '10.0.0.1', ['10.0.0.0/8'], True, id='address-belongs'),
    param(False, '10.1.0.2', ['10.0.0.0/16'], False,
          id='address-does-not-belong'),
    param(False, '10.1.0.3', ['10.0.0.0/16', '10.1.0.0/16'], True,
          id='address-belongs-in-one')
])
def test_etcd_reachable_from_endpoint(mocker, bind_all, ingress_addr,
                                      endpoint_net, expected):
    """Test etcd_reachable_from_endpoint in various scenarios."""
    endpoint_networks = {'addresses':
                         [{'cidr': network} for network in endpoint_net]
                         }
    addr_in_network = any([(IPAddress(ingress_addr) in IPNetwork(net)) for net
                           in endpoint_net])
    mocker.patch.object(etcd_lib, 'config', return_value=bind_all)
    mocker.patch.object(etcd_lib, 'network_get', return_value=endpoint_networks)
    mocker.patch.object(etcd_lib, 'get_ingress_address',
                        return_value=ingress_addr)
    mocker.patch.object(etcd_lib, 'is_address_in_network',
                        return_value=addr_in_network)

    is_reachable = etcd_reachable_from_endpoint('foo')

    assert is_reachable == expected


def test_render_grafana_dashboard():
    """Test loading of Grafana dashboard."""
    datasource = 'prometheus'
    hookenv.charm_dir.return_value = './'
    raw_template = b'{"panels": [{"datasource": "<< datasource >>"}]}'
    expected_dashboard = {
        'panels': [
            {'datasource': '{} - Juju generated source'.format(datasource)}
        ]}

    with patch('builtins.open', mock_open(read_data=raw_template)):
        rendered_dashboard = render_grafana_dashboard(datasource)

    assert rendered_dashboard == expected_dashboard
