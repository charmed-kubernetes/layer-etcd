from typing import Any
from unittest import mock

from charmhelpers.contrib.templating import jinja
import charmhelpers.core.hookenv as hookenv
import pytest

from etcd_lib import build_uri, get_bind_address, render_grafana_dashboard


def test_render_grafana_dashboard():
    """Test loading of Grafana dashboard."""
    datasource = "prometheus"
    raw_template = (
        '{{"panels": [{{"datasource": "{} - '
        'Juju generated source"}}]}}'.format(datasource)
    )
    expected_dashboard = {
        "panels": [{"datasource": "{} - Juju generated source".format(datasource)}]
    }

    jinja.render.return_value = raw_template
    rendered_dashboard = render_grafana_dashboard(datasource)

    assert rendered_dashboard == expected_dashboard


@pytest.mark.parametrize(
    "src,result",
    [
        ("1.2.3.4", "https://1.2.3.4:8080"),
        ("2001:0db8::0001", "https://[2001:db8::1]:8080"),
        ("my.host.io", "https://my.host.io:8080"),
    ],
)
def test_build_uri(src: Any, result: str):
    assert build_uri("https", src, 8080) == result


@pytest.fixture
def unit_private_ip():
    hookenv.unit_private_ip.reset_mock()
    return hookenv.unit_private_ip


def test_get_bind_address_fails_network_get(unit_private_ip):
    with mock.patch("etcd_lib.network_get", side_effect=NotImplementedError):
        assert get_bind_address("test") == unit_private_ip.return_value
    unit_private_ip.assert_called_once_with()


def test_get_bind_address_empty_bind_address(unit_private_ip):
    with mock.patch("etcd_lib.network_get", return_value={}):
        assert get_bind_address("test") == unit_private_ip.return_value
    unit_private_ip.assert_called_once_with()


def test_get_bind_address_picks_v4_first(unit_private_ip):
    ipv4 = "1.2.3.4"
    bind_data = {
        "bind-addresses": [
            {
                "macaddress": "02:d0:9e:31:d9:e0",
                "interfacename": "ens5",
                "addresses": [
                    {
                        "hostname": "",
                        "address": "2002::1234:abcd:ffff:c0a8:101",
                        "cidr": "2002::1234:abcd:ffff:c0a8:101/64",
                    },
                    {"hostname": "", "address": ipv4, "cidr": f"{ipv4}/20"},
                ],
            }
        ]
    }
    with mock.patch("etcd_lib.network_get", return_value=bind_data):
        assert get_bind_address("test") == ipv4
    unit_private_ip.assert_not_called()


def test_get_bind_address_picks_v6(unit_private_ip):
    ipv6 = "2002::1234:abcd:ffff:c0a8:101"
    bind_data = {
        "bind-addresses": [
            {
                "macaddress": "",
                "interfacename": "ens5",
                "addresses": [{"hostname": "", "address": ipv6, "cidr": f"{ipv6}/64"}],
            }
        ]
    }
    with mock.patch("etcd_lib.network_get", return_value=bind_data):
        assert get_bind_address("test") == ipv6
    unit_private_ip.assert_not_called()
