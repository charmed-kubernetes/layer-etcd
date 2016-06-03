from charmhelpers.core.hookenv import log
from subprocess import CalledProcessError
from shlex import split
from subprocess import check_output
import os


class EtcdCtl:
    ''' etcdctl modeled as a python class. This python wrapper consumes
    and exposes some of the commands contained in etcdctl. Related to unit
    registration, cluster health, and other operations '''

    def register(self, cluster_data):
        ''' Perform self registration against the etcd leader and returns the
        raw output response.

        @params cluster_data - a dict of data to fill out the request to
        push our registration to the leader
        requires keys: leader_address, port, unit_name, private_address,
        management_port
        '''
        command = "etcdctl -C {} member add {}" \
                  " http://{}:{}".format(cluster_data['leader_address'],
                                         cluster_data['unit_name'],
                                         cluster_data['private_address'],
                                         cluster_data['management_port'])

        try:
            result = self.run(command)
        except CalledProcessError:
            log('Notice:  Unit failed self registration', 'WARNING')
            return

        # ['Added member named etcd12 with ID b9ab5b5a2e4baec5 to cluster',
        # '', 'ETCD_NAME="etcd12"',
        #  'ETCD_INITIAL_CLUSTER="etcd11=https://10.113.96.26:2380,etcd12=http://10.113.96.206:2380"',
        # 'ETCD_INITIAL_CLUSTER_STATE="existing"', '']

        reg = {}

        for line in result.split('\n'):
            if 'Added member' in line:
                reg['cluster_unit_id'] = line.split('ID')[-1].strip(' ').split(' ')[0]  # noqa
            if 'ETCD_INITIAL_CLUSTER=' in line:
                reg['cluster'] = line.split('="')[-1].rstrip('"')
        return reg

    def unregister(self, unit_id):
        ''' Perform self deregistration during unit teardown

        @params cluster_data - a dict of data to fill out the request to push
        our deregister command to the leader. requires  keys: leader_address,
        port, etcd_unit_guid

        The unit_id can be obtained from the EtcdDatabag dict
        '''
        command = "etcdctl member remove {}".format(unit_id)

        return self.run(command)

    def member_list(self, leader_address=None):
        ''' Returns the output from `etcdctl member list` as a python dict
        organized by unit_name, containing all the data-points in the resulting
        response. '''

        members = {}
        if leader_address:
            cmd = "etcdctl --endpoint {} member list".format(leader_address)
            out = self.run(cmd)
        else:
            out = self.run("etcdctl member list")
        raw_member_list = out.strip('\n').split('\n')
        # Expect output like this:
        # 4f24ee16c889f6c1: name=etcd20 peerURLs=https://10.113.96.197:2380 clientURLs=https://10.113.96.197:2379  # noqa
        # edc04bb81479d7e8: name=etcd21 peerURLs=https://10.113.96.243:2380 clientURLs=https://10.113.96.243:2379  # noqa

        for unit in raw_member_list:
            if '[unstarted]' in unit:
                members['unstarted'] = {}
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

    def cluster_health(self):
        ''' Returns the output of etcdctl cluster-health as a python dict
        organized by topical information with detailed unit output '''

        out = self.run('etcdctl cluster-health')
        health_output = out.strip('\n').split('\n')
        return {'status': health_output[-1], 'units': health_output[0:-2]}

    def run(self, command):
        ''' Wrapper to subprocess calling output. This is a convenience
        method to clean up the calls to subprocess and append TLS data'''
        os.environ['ETCDCTL_CA_FILE'] = '/etc/ssl/etcd/ca.pem'
        os.environ['ETCDCTL_CERT_FILE'] = '/etc/ssl/etcd/server.pem'
        os.environ['ETCDCTL_KEY_FILE'] = '/etc/ssl/etcd/server-key.pem'
        return check_output(split(command)).decode('ascii')
