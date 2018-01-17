from charmhelpers.core.hookenv import network_get, unit_private_ip


def get_ingress_address(endpoint_name):
    ''' Returns ingress-address belonging to the named endpoint, if available.
    Falls back to private-address if necessary. '''
    try:
        data = network_get(endpoint_name)
    except NotImplementedError:
        return unit_private_ip()

    if 'ingress-addresses' in data:
        return data['ingress-addresses'][0]
    else:
        return unit_private_ip()
