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

Its recommended to run an odd number of machines as it has greater redundancy
than even number (ie. with 4, you can lose 1 before quorum is lost, where as
with 5, you can lose 2).

# The charm told me to see the README

You've been directed here because you're deploying this etcd charm onto a
pre-Xenial and non-amd64-based Ubuntu platform, and we don't have etcd and
etcdctl binaries for that platform. You will need to obtain such binaries
somehow yourself (e.g. by downloading and building from source), then tell
Juju about those binaries as detailed below.

## Usage with your own binaries

This charm supports resources, which means you can supply your own release of
etcd and etcdctl to this charm. Which by nature makes it highly deployable on
multiple architectures.

### Supply your own binaries

```shell
juju upgrade-charm etcd --resource etcd=./path/to/etcd --resource etcdtcl=./path/to/etcdctl
juju list-resources etcd
```

You will see your binaries have been provided by username@local, and the charm
will reconfigure itself to deploy the provided binaries.

### To test the binaries (an example for amd64 hosts)

If you are simply deploying etcd, and the charm has halted demanding resources
by telling you to consult the README, you can use a script contained in the
charm itself.

```shell
charm pull etcd
cd etcd
make fetch_resources
...
cd resources
cd tar xvfz etcd*.tar.gz
```

You can then upgrade the charm using the resources found in this extracted
archive. Only the binaries will be necessary, you can safely ignore any
additional files.

# Health
Health of the cluster can be checked by verified via juju actions

```shell
juju action do etcd/0 health
<return response uuid>
juju action fetch <uuid>

```

The health is also reported continuously via `juju status`. During initial
cluster turn-up, its entirely reasonable for the health checks to fail. this
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

### Notes about cluster turn-up

The Etcd charm initializes a cluster using the Static configuration: which
is the most "flexible" of all the installation options, considering it allows
Etcd to be self-discovering using the peering relationships provided by
Juju. Trying to start up etcd behind the corporate firewall? Thanks to
resources, the charm is now completely stand alone, and supports this.



# Known Limitations

Scaling up works incredibly well. Scaling down however has proven problematic.
The nodes do their best attempt to self-unregister; however the cluster can find
itself in an inconsistent state with the current peering mechanisms.

This is a known issue and you are encouraged to only scale Etcd up until [this
problem has been resolved](https://github.com/juju-solutions/layer-etcd/issues/5).

This charm requires resources to be provided to the charm in order to deploy
on trusty hosts. This requires juju 2.0 or greater.

If you destroy the leader - identified with the `(leader)` text prepended to
any status messages: all TLS pki will be lost. No PKI migration occurs outside
of the units requesting and registering the certificates. You have been warned.


## Contributors

- Charles Butler &lt;[charles.butler@canonical.com](mailto:charles.butler@canonical.com)&gt;
