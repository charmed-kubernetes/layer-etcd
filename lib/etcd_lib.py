from charmhelpers.contrib.network.ip import is_address_in_network
from charmhelpers.core.hookenv import (
    charm_dir,
    config,
    log,
    network_get,
    unit_private_ip,
)

from jinja2 import Environment, FileSystemLoader
from jinja2.exceptions import TemplateNotFound

import json
import os


GRAFANA_DASHBOARD_FILE = 'grafana_dashboard.json.j2'


def get_ingress_addresses(endpoint_name):
    ''' Returns all ingress-addresses belonging to the named endpoint, if
    available. Falls back to private-address if necessary. '''
    try:
        data = network_get(endpoint_name)
    except NotImplementedError:
        return [unit_private_ip()]

    if 'ingress-addresses' in data:
        return data['ingress-addresses']
    else:
        return [unit_private_ip()]


def get_ingress_address(endpoint_name):
    ''' Returns an ingress-address belonging to the named endpoint, if
    available. Falls back to private-address if necessary. '''
    return get_ingress_addresses(endpoint_name)[0]


def get_bind_address(endpoint_name):
    ''' Returns the first bind-address found in network info
    belonging to the named endpoint, if available.
    Falls back to private-address if necessary.

        @param endpoint_name the endpoint from where taking the
        bind address
    '''
    try:
        data = network_get(endpoint_name)
    except NotImplementedError:
        return unit_private_ip()

    # Consider that network-get returns something like:
    #
    # bind-addresses:
    # - macaddress: 02:d0:9e:31:d9:e0
    # interfacename: ens5
    # addresses:
    # - hostname: ""
    #     address: 172.31.5.4
    #     cidr: 172.31.0.0/20
    # - hostname: ""
    #     address: 172.31.5.4
    #     cidr: 172.31.0.0/20
    # - macaddress: 8a:32:d7:8d:f6:9a
    # interfacename: fan-252
    # addresses:
    # - hostname: ""
    #     address: 252.5.4.1
    #     cidr: 252.0.0.0/12
    # egress-subnets:
    # - 172.31.5.4/32
    # ingress-addresses:
    # - 172.31.5.4
    # - 172.31.5.4
    # - 252.5.4.1
    if 'bind-addresses' in data:
        bind_addresses = data['bind-addresses']
        if len(bind_addresses) > 0:
            if 'addresses' in bind_addresses[0]:
                if len(bind_addresses[0]['addresses']) > 0:
                    return bind_addresses[0]['addresses'][0]['address']

    return unit_private_ip()


def etcd_reachable_from_endpoint(endpoint_name):
    """Check if etcd can be reached by unit on the other end of the relation.

    :param endpoint_name: Name of the relation endpoint
    :return: True/False depending on whether the etcd service can be reached
    """
    if config(scope='bind_to_all_interfaces'):
        return True

    endpoint_addresses = network_get(endpoint_name).get('addresses', [])
    if not endpoint_addresses:
        return False

    ingress_address = get_ingress_address('db')

    for cidr in [address['cidr'] for address in endpoint_addresses]:
        if is_address_in_network(cidr, ingress_address):
            return True

    return False


def render_grafana_dashboard(datasource):
    """Load grafana dashboard json model and insert prometheus datasource.

    :param datasource: name of the 'prometheus' application that will be used
                       as datasource in grafana dashboard
    :return: Grafana dashboard json model as a dict.
    """
    datasource = "{} - Juju generated source".format(datasource)

    template_folder = os.path.join(charm_dir(), "templates/")

    environment = Environment(loader=FileSystemLoader(template_folder),
                              variable_start_string="<<",
                              variable_end_string=">>"
                              )
    try:
        template = environment.get_template(GRAFANA_DASHBOARD_FILE)
    except TemplateNotFound as exc:
        log(
            "Could not load template {} from {}".format(GRAFANA_DASHBOARD_FILE,
                                                        template_folder)
        )
        raise exc
    return json.loads(template.render({'datasource': datasource}))
