from charms import layer
from charmhelpers.core.hookenv import log
from subprocess import CalledProcessError
from shlex import split
from subprocess import check_output
import os


def etcdctl_command():
    if os.path.isfile('/snap/bin/etcd.etcdctl'):
        return '/snap/bin/etcd.etcdctl'
    return 'etcdctl'


class EtcdCtl:
    ''' etcdctl modeled as a python class. This python wrapper consumes
    and exposes some of the commands contained in etcdctl. Related to unit
    registration, cluster health, and other operations '''
    class CommandFailed(Exception):
        pass

    def register(self, cluster_data):
        ''' Perform self registration against the etcd leader and returns the
        raw output response.

        @params cluster_data - a dict of data to fill out the request to
        push our registration to the leader
        requires keys: leader_address, port, unit_name, cluster_address,
        management_port
        '''
        # Build a connection string for the cluster data.
        connection = get_connection_string([cluster_data['cluster_address']],
                                           cluster_data['management_port'])
        # Create a https url to the leader unit name on the private addres.
        command = "{3} -C {0} member add {1} " \
                  "{2}".format(cluster_data['leader_address'],
                               cluster_data['unit_name'],
                               connection, etcdctl_command())

        try:
            result = self.run(command)
        except EtcdCtl.CommandFailed:
            log('Notice:  Unit failed self registration', 'WARNING')
            raise

        # ['Added member named etcd12 with ID b9ab5b5a2e4baec5 to cluster',
        # '', 'ETCD_NAME="etcd12"',
        #  'ETCD_INITIAL_CLUSTER="etcd11=https://10.113.96.26:2380,etcd12=https://10.113.96.206:2380"',  # noqa
        # 'ETCD_INITIAL_CLUSTER_STATE="existing"', '']

        reg = {}

        for line in result.split('\n'):
            if 'ETCD_INITIAL_CLUSTER=' in line:
                reg['cluster'] = line.split('="')[-1].rstrip('"')
        return reg

    def unregister(self, unit_id, leader_address=None):
        ''' Perform self deregistration during unit teardown

        @params unit_id - the ID for the unit assigned by etcd. Obtainable from
        member_list method.

        @params leader_address - The endpoint to communicate with the leader in
        the event of self deregistration.
        '''

        if leader_address:
            cmd = "{0} --endpoints {1} member remove {2}"
            command = cmd.format(etcdctl_command(), leader_address, unit_id)
        else:
            cmd = "{0} member remove {1}"
            command = cmd.format(etcdctl_command(), unit_id)

        return self.run(command)

    def member_list(self, leader_address=None):
        ''' Returns the output from `etcdctl member list` as a python dict
        organized by unit_name, containing all the data-points in the resulting
        response. '''

        members = {}
        out = self.run('member list', endpoints=leader_address)
        raw_member_list = out.strip('\n').split('\n')
        # Expect output like this:
        # 4f24ee16c889f6c1: name=etcd20 peerURLs=https://10.113.96.197:2380 clientURLs=https://10.113.96.197:2379  # noqa
        # edc04bb81479d7e8: name=etcd21 peerURLs=https://10.113.96.243:2380 clientURLs=https://10.113.96.243:2379  # noqa
        # edc0dsa81479d7e8[unstarted]: peerURLs=https://10.113.96.124:2380  # noqa

        for unit in raw_member_list:
            if '[unstarted]' in unit:
                unit_guid = unit.split('[')[0]
                members['unstarted'] = {'unit_id': unit_guid}
                if 'peerURLs=' in unit:
                    peer_urls = unit.split(' ')[1].split("=")[-1]
                    members['unstarted']['peer_urls'] = peer_urls
                continue
            unit_guid = unit.split(':')[0]
            unit_name = unit.split(' ')[1].split("=")[-1]
            peer_urls = unit.split(' ')[2].split("=")[-1]
            client_urls = unit.split(' ')[3].split("=")[-1]

            members[unit_name] = {'unit_id': unit_guid,
                                  'name': unit_name,
                                  'peer_urls': peer_urls,
                                  'client_urls': client_urls}
        return members

    def member_update(self, unit_id, uri):
        ''' Update the etcd cluster member by unit_id with a new uri. This
        allows us to change protocol, address or port.
        @params unit_id: The string ID of the unit in the cluster.
        @params uri: The string universal resource indicator of where to
        contact the peer. '''
        out = ''
        try:
            command = 'member update {} {}'.format(unit_id, uri)
            log(command)
            # Run the member update command for the existing unit_id.
            out = self.run(command)
        except EtcdCtl.CommandFailed:
            log('Failed to update member {0}'.format(unit_id), 'WARNING')
        return out

    def cluster_health(self):
        ''' Returns the output of etcdctl cluster-health as a python dict
        organized by topical information with detailed unit output '''
        health = {}
        try:
            out = self.run('cluster-health')
            health_output = out.strip('\n').split('\n')
            health['status'] = health_output[-1]
            health['units'] = health_output[0:-2]
        except EtcdCtl.CommandFailed:
            log('Notice:  Unit failed cluster-health check', 'WARNING')
            health['status'] = 'cluster is unhealthy see log file for details.'
            health['units'] = []
        return health

    def run(self, arguments, endpoints=None):
        ''' Wrapper to subprocess calling output. This is a convenience
        method to clean up the calls to subprocess and append TLS data'''
        env = {}
        command = [etcdctl_command()]
        opts = layer.options('tls-client')
        ca_path = opts['ca_certificate_path']
        crt_path = opts['server_certificate_path']
        key_path = opts['server_key_path']

        major, _, _ = self.version().split('.')

        if int(major) >= 3:
            env['ETCDCTL_API'] = '3'
            env['ETCDCTL_CACERT'] = ca_path
            env['ETCDCTL_CERT'] = crt_path
            env['ETCDCTL_KEY'] = key_path
            if endpoints is None:
                endpoints = 'http://127.0.0.1:4001'

        elif int(major) == 2:
            env['ETCDCTL_API'] = '2'
            env['ETCDCTL_CA_FILE'] = ca_path
            env['ETCDCTL_CERT_FILE'] = crt_path
            env['ETCDCTL_KEY_FILE'] = key_path
            if endpoints is None:
                endpoints = ':4001'

        else:
            raise NotImplementedError(
                'etcd version {} not supported'.format(major))

        if isinstance(arguments, str):
            command.extend(arguments.split())
        elif isinstance(arguments, list) or isinstance(arguments, tuple):
            command.extend(arguments)
        else:
            raise RuntimeError(
                'arguments not correct type; must be string, list or tuple')

        if endpoints is not False:
            command.extend(['--endpoints={}'.format(endpoints)])

        try:
            return check_output(
                command,
                env=env
            ).decode('ascii')
        except CalledProcessError as e:
            log(e.output)
            raise EtcdCtl.CommandFailed() from e

    def version(self):
        ''' Return the version of etcdctl '''
        out = check_output(
            [etcdctl_command(), 'version'],
            env={'ETCDCTL_API': '3'}
        ).decode('utf-8')

        if out == "No help topic for 'version'\n":
            # Probably on etcd2
            out = check_output(
                [etcdctl_command(), '--version']
            ).decode('utf-8')

        return out.split('\n')[0].split()[2]


def get_connection_string(members, port, protocol='https'):
    ''' Return a connection string for the list of members using the provided
    port and protocol (defaults to https)'''
    connections = []
    for address in members:
        connections.append('{0}://{1}:{2}'.format(protocol, address, port))
    connection_string = ','.join(connections)
    return connection_string
