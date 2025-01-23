from jinja2 import FileSystemLoader, Environment
from unittest import mock
import pytest

from charms.unit_test import MockKV
import reactive.etcd
import etcd_databag


@pytest.fixture
def config():
    kv = MockKV()
    reactive.etcd.config.reset_mock()
    reactive.etcd.config.side_effect = kv.get
    reactive.etcd.config.set = kv.set
    return reactive.etcd.config


@pytest.fixture
def bind_address(config):
    config.set("bind_to_all_interfaces", False)
    IP = dict(cluster="1.1.1.1", db="2001:0dc8::0001")
    with mock.patch(
        "etcd_databag.get_bind_address", side_effect=lambda name: IP.get(name)
    ) as mocked:
        yield mocked


@pytest.fixture
def ingress_address():
    IP = dict(cluster="2.2.2.2", db="4001:0084::0001")
    with mock.patch(
        "etcd_databag.get_ingress_address", side_effect=lambda name: IP.get(name)
    ) as mocked:
        yield mocked


def test_render_etcd2(
    config,
    bind_address,
    ingress_address,
):
    config.set("management_port", 1234)
    config.set("port", 5678)
    config.set("bind_with_insecure_http", True)
    config.set("channel", "3.2/stable")
    config.set("snapshot_count", "auto")
    bag = etcd_databag.EtcdDatabag()
    template_env = Environment(loader=FileSystemLoader("templates"))
    config = template_env.get_template("etcd2.conf").render(bag.__dict__)
    lines = config.splitlines()
    assert 'ETCD_ADVERTISE_CLIENT_URLS="https://[4001:84::1]:5678"' in lines
    assert (
        'ETCD_LISTEN_CLIENT_URLS="http://127.0.0.1:4001,https://[2001:dc8::1]:5678"'
        in lines
    )
    assert 'ETCD_LISTEN_PEER_URLS="https://1.1.1.1:1234"' in lines
    assert 'ETCD_INITIAL_ADVERTISE_PEER_URLS="https://2.2.2.2:1234"' in lines


def test_render_etcd3(
    config,
    bind_address,
    ingress_address,
):
    config.set("management_port", 1234)
    config.set("port", 5678)
    config.set("bind_with_insecure_http", True)
    config.set("channel", "3.2/stable")
    config.set("snapshot_count", "auto")
    bag = etcd_databag.EtcdDatabag()
    template_env = Environment(loader=FileSystemLoader("templates"))
    config = template_env.get_template("etcd3.conf").render(bag.__dict__)
    lines = config.splitlines()
    assert "advertise-client-urls: https://[4001:84::1]:5678" in lines
    assert (
        "listen-client-urls: http://127.0.0.1:4001,https://[2001:dc8::1]:5678" in lines
    )
    assert "listen-peer-urls: https://1.1.1.1:1234" in lines
    assert "initial-advertise-peer-urls: https://2.2.2.2:1234" in lines
