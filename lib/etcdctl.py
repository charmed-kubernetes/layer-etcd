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
        except CalledProcessError:
            log('Notice:  Unit failed self registration', 'WARNING')
            return

        # ['Added member named etcd12 with ID b9ab5b5a2e4baec5 to cluster',
        # '', 'ETCD_NAME="etcd12"',
        #  'ETCD_INITIAL_CLUSTER="etcd11=https://10.113.96.26:2380,etcd12=https://10.113.96.206:2380"',  # noqa
        # 'ETCD_INITIAL_CLUSTER_STATE="existing"', '']

        reg = {}

        for line in result.split('\n'):
            if 'Added member' in line:
                reg['cluster_unit_id'] = line.split('ID')[-1].strip(' ').split(' ')[0]  # noqa
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
            cmd = "{0} --endpoint {1} member remove {2}"
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
        if leader_address:
            cmd = "{0} --endpoint {1} member list".format(etcdctl_command(),
                                                          leader_address)
            out = self.run(cmd)
        else:
            out = self.run("{} member list".format(etcdctl_command()))
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
                    members['peer_urls'] = peer_urls
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
            cmd = '{2} member update {0} {1}'
            command = cmd.format(unit_id, uri, etcdctl_command())
            log(command)
            # Run the member update command for the existing unit_id.
            out = self.run(command)
        except CalledProcessError as cpe:
            log('Failed to update member {0}'.format(unit_id), 'WARNING')
            log(cpe.output)
        return out

    def cluster_health(self):
        ''' Returns the output of etcdctl cluster-health as a python dict
        organized by topical information with detailed unit output '''
        health = {}
        try:
            out = self.run('{} cluster-health'.format(etcdctl_command()))
            health_output = out.strip('\n').split('\n')
            health['status'] = health_output[-1]
            health['units'] = health_output[0:-2]
        except CalledProcessError as cpe:
            log('Notice:  Unit failed cluster-health check', 'WARNING')
            log(cpe.output)
            health['status'] = 'cluster is unhealthy see log file for details.'
            health['units'] = []
        return health

    def run(self, command):
        ''' Wrapper to subprocess calling output. This is a convenience
        method to clean up the calls to subprocess and append TLS data'''
        opts = layer.options('tls-client')
        ca_path = opts['ca_certificate_path']
        crt_path = opts['server_certificate_path']
        key_path = opts['server_key_path']
        os.environ['ETCDCTL_CA_FILE'] = ca_path
        os.environ['ETCDCTL_CERT_FILE'] = crt_path
        os.environ['ETCDCTL_KEY_FILE'] = key_path
        return check_output(split(command)).decode('ascii')

    def version(self):
        ''' Return the version of etcdctl '''
        version = ''
        out = self.run('{} --version'.format(etcdctl_command()))

        for line in out.split('\n'):
            if 'etcdctl' in line:
                # Note: version 2 does not contain any : so split on version
                # and handle etcd 3+ output accordingly.
                version = line.split('version')[-1].replace(':', '').strip()
        return version


def get_connection_string(members, port, protocol='https'):
    ''' Return a connection string for the list of members using the provided
    port and protocol (defaults to https)'''
    connections = []
    for address in members:
        connections.append('{0}://{1}:{2}'.format(protocol, address, port))
    connection_string = ','.join(connections)
    return connection_string
