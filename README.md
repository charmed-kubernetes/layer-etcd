# Etcd

Etcd is a highly available distributed key value store that provides a reliable
way to store data across a cluster of machines. Etcd gracefully handles master
elections during network partitions and will tolerate machine failure,
including the master.

Your applications can read and write data into Etcd. A simple use-case is to
store database connection details or feature flags in Etcd as key value pairs.
These values can be watched, allowing your app to reconfigure itself when they
change.

Advanced uses take advantage of the consistency guarantees to implement
database master elections or do distributed locking across a cluster of
workers.

Etcd allows storing data in a distributed hierarchical database with
observation.

# Usage

We can deploy a single node easily with

```shell
juju deploy etcd
```
And add capacity with:

```shell
juju add-unit -n 2 etcd
```

It's recommended to run an odd number of machines as it has greater redundancy
than an even number (i.e. with 4, you can lose 1 before quorum is lost, whereas
with 5, you can lose 2).

### Notes about cluster turn-up

The Etcd charm initializes a cluster using the Static configuration: which
is the most "flexible" of all the installation options, considering it allows
Etcd to be self-discovering using the peering relationships provided by
Juju.

# Health
Health of the cluster can be checked by verified via juju actions

```shell
juju action do etcd/0 health
<return response uuid>
juju action fetch <uuid>

```

The health is also reported continuously via `juju status`. During initial
cluster turn-up, it's entirely reasonable for the health checks to fail; this
is not a situation to cause you alarm. The health-checks are being executed
before the cluster has stabilized, and it should even out once the members
start to come online and the update-status hook is run again.

This will give you some insight into the cluster on a 5 minute interval, and
will report healthy nodes vs unhealthy nodes.

For example:

```shell
ID      WORKLOAD-STATUS JUJU-STATUS VERSION   MACHINE PORTS             PUBLIC-ADDRESS MESSAGE
etcd/9  active          idle        2.0-beta6 10      2379/tcp,2380/tcp 192.168.239.20 cluster-health check failed... needs attention
etcd/10 active          idle        2.0-beta6 9       2379/tcp,2380/tcp 192.168.91.60  (leader) cluster is healthy
```

# TLS

The ETCD charm supports TLS terminated endpoints by default. All efforts have
been made to ensure the PKI is as robust as possible.

Client certificates can be obtained by running an action on any of the cluster
members:

```shell
juju run-action etcd/12 generate-client-certificates
juju scp etcd/12:etcd_client_credentials.tar.gz etcd_credentials.tar.gz
```

This will place the client certificates in `pwd`. If you're keen on using
etcdctl outside of the cluster machines,  you'll need to expose the service,
and export some environment variables to consume the client credentials.

```shell
juju expose etcd
export ETCDCTL_KEY_FILE=$(pwd)/clientkey.pem
export ETCDCTL_CERT_FILE=$(pwd)/clientcert.pem
export ETCDCTL_CA_FILE=$(pwd)/ca.pem
export ETCDCTL_ENDPOINT=https://{ip of etcd host}:2379
etcdctl member list
```

# Operational Actions

### Snapshot

Allows the operator to snapshot a running clusters data for use in cloning,
backing up, or migrating Etcd clusters. 

```
juju run-action etcd/0 snapshot target=/mnt/etcd-backups
```

- **param** target: destination directory to save the resulting snapshot archive.

# Known Limitations

If you destroy the leader - identified with the `*` text next to the unit number:
all TLS pki will be lost. No PKI migration occurs outside
of the units requesting and registering the certificates. You have been warned.

Additionally, this charm breaks with no backwords compat/upgrade path at the trusty/xenial
series boundary. Xenial forward will enable TLS by default. This is an incompatible break
due to the nature of peer relationships, and how the certificates are generated/passed off.

To migrate from trusty to xenial, the operator will be responsible for deploying the
xenial etcd cluster, then issuing an etcd data dump on the trusty series, and importing
that data into the new cluster. This can be performed on a single node due to the
nature of how replicas work in Etcd.

Any issues with the above process should be filed against the charm layer in github.

## Contributors

- Charles Butler &lt;[charles.butler@canonical.com](mailto:charles.butler@canonical.com)&gt;
- Mathew Bruzek  &lt;[mathew.bruzek@canonical.com](mailto:mathew.bruzek@canonical.com)&gt;
