from charmhelpers.core.hookenv import network_get, unit_private_ip


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
