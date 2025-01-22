from ipaddress import ip_address

from charmhelpers.contrib.templating.jinja import render
from charmhelpers.core.hookenv import (
    network_get,
    unit_private_ip,
)

import json

GRAFANA_DASHBOARD_FILE = "grafana_dashboard.json.j2"


def build_uri(schema, address, port) -> str:
    """Build uris with ipv6 addresses in square-brakets []."""
    try:
        address = ip_address(address)
    except ValueError:
        pass
    else:
        if address.version == 6:
            address = f"[{address}]"
    return f"{schema}://{address}:{port}"


def get_ingress_addresses(endpoint_name):
    """Returns all ingress-addresses belonging to the named endpoint, if
    available. Falls back to private-address if necessary."""
    try:
        data = network_get(endpoint_name)
    except NotImplementedError:
        return [unit_private_ip()]

    if "ingress-addresses" in data:
        return data["ingress-addresses"]
    else:
        return [unit_private_ip()]


def get_ingress_address(endpoint_name):
    """Returns an ingress-address belonging to the named endpoint.

    * Sort addresses by ipv4 first, then ipv6 next
    * Falls back to private-address if necessary.
    """
    all_addrs = get_ingress_addresses(endpoint_name)
    return sorted(all_addrs, key=lambda i: ip_address(i).version)[0]


def get_snapshot_count(snapshot_count: str, channel: str) -> int:
    """Returns the snapshot count value

    * check if the value is auto,
        iff channel >=3.2 it will set 100'000 otherwhise it will set 10'000
    * any other integer value will be set as it is

    @param snapshot_count the value to set, could be a number or auto
    @param channel the channel used by the charm
    """
    if snapshot_count == "auto":
        if channel == "auto" or float(channel.split("/")[0]) >= 3.2:
            return 100000
        return 10000
    try:
        return int(snapshot_count)
    except ValueError:
        raise TypeError(f"{snapshot_count} value is not an integer number")


def get_bind_address(endpoint_name):
    """Returns the first bind-address found in network info
    belonging to the named endpoint, if available.
    Falls back to private-address if necessary.

    * Sort addresses by ipv4 first, then ipv6 next

    @param endpoint_name the endpoint from where taking the
    bind address
    """
    try:
        data = network_get(endpoint_name)
    except NotImplementedError:
        return unit_private_ip()

    # Consider that network-get returns something like:
    #
    # bind-addresses:
    # - macaddress: 02:d0:9e:31:d9:e0
    #   interfacename: ens5
    #   addresses:
    #   - hostname: ""
    #     address: 172.31.5.4
    #     cidr: 172.31.0.0/20
    #   - hostname: ""
    #     address: 172.31.5.4
    #     cidr: 172.31.0.0/20
    # - macaddress: 8a:32:d7:8d:f6:9a
    #   interfacename: fan-252
    #   addresses:
    #   - hostname: ""
    #     address: 252.5.4.1
    #     cidr: 252.0.0.0/12
    # egress-subnets:
    # - 172.31.5.4/32
    # ingress-addresses:
    # - 172.31.5.4
    # - 172.31.5.4
    # - 252.5.4.1
    interfaces = data.get("bind-addresses", [])
    addresses = []

    if interfaces:
        addresses = sorted(
            [
                ip_address(addr["address"])
                for ifc in interfaces
                for addr in ifc.get("addresses", [])
                if "address" in addr
            ],
            key=lambda addr: addr.version,
        )
    if addresses:
        return str(addresses[0])

    return unit_private_ip()


def render_grafana_dashboard(datasource):
    """Load grafana dashboard json model and insert prometheus datasource.

    :param datasource: name of the 'prometheus' application that will be used
                       as datasource in grafana dashboard
    :return: Grafana dashboard json model as a dict.
    """
    datasource = "{} - Juju generated source".format(datasource)
    jinja_args = {"variable_start_string": "<<", "variable_end_string": ">>"}
    return json.loads(
        render(
            GRAFANA_DASHBOARD_FILE,
            {"datasource": datasource},
            jinja_env_args=jinja_args,
        )
    )
