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
juju deploy easyrsa
juju deploy etcd
juju add-relation etcd easyrsa
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
export ETCDCTL_KEY_FILE=$(pwd)/client.key
export ETCDCTL_CERT_FILE=$(pwd)/client.crt
export ETCDCTL_CA_FILE=$(pwd)/ca.crt
export ETCDCTL_ENDPOINT=https://{ip of etcd host}:2379
etcdctl member list
```

# Persistent Storage

Many cloud providers use ephemeral storage. It's usually a good idea to place
any data-stores when using cloud provider infrastructure on persistent volumes
that exist outside of the ephemeral storage on the unit.

Juju abstracts this with the [storage provider](https://jujucharms.com/docs/stable/charms-storage)


To add a unit of storage we'll first need to discover what storage types the
cloud provides to us, which can be discerned with:
```
juju list-storage-pools
```

#### AWS Storage example

To add SSD backed EBS storage from AWS, the following example provisions a
single 10GB SSD EBS instance and attaches it to the etcd/0 unit.

```
juju add-storage etcd/0 data=ebs-ssd,10G
```

#### GCE Storage example

To add Persistent Disk storage from GCE, the following example
provisions a single 10GB PD instance and attaches it to the etcd/0 unit.

```
juju add-storage etcd/0 data=gce,10G
```

#### Cinder Storage example

To add Persistent Disk storage from Open Stack Cinder, the following example
provisions a single 10GB PD instance and attaches it to the etcd/0 unit.

```
juju add-storage etcd/0 data=cinder,10G
```

# Operational Actions

### Restore

Allows the operator to restore the data from a cluster-data snapshot. This
comes with caveats and a very specific path to restore a cluster:

The cluster must be in a state of only having a single member. So it's best to
deploy a new cluster using the etcd charm, without adding any additional units.

```
juju deploy etcd new-etcd
```

> The above code snippet will deploy a single unit of etcd, as 'new-etcd'

```
juju run-action etcd/0 restore target=/mnt/etcd-backups
```

Once the restore action has completed, evaluate the cluster health. If the unit
is healthy, you may resume scaling the application to meet your needs.


- **param** target: destination directory to save the existing data.

- **param** skip-backup: Don't backup any existing data.

### Snapshot

Allows the operator to snapshot a running clusters data for use in cloning,
backing up, or migrating Etcd clusters.

```
juju run-action etcd/0 snapshot target=/mnt/etcd-backups
```

- **param** target: destination directory to save the resulting snapshot archive.



# Migrating etcd

Migrating Etcd is a fairly easy task. The process is mostly copy/pasteable.

Step 1: Snapshot your existing cluster. This is encapsuluted in the `snapshot`
action.

```
$ juju run-action etcd/0 snapshot

Action queued with id: b46d5d6f-5625-4320-8cda-b611c6ae580c
```

Step 2: check the status of the action so you can grab the snapshot and verify
the sum. The copy.cmd result ouput is a copy/paste command for you to download
the exact snapshot that you just created.

Download the snapshot tarball from the unit that created the snapshot and verify
the sha256 sum

```
$ juju show-action-output b46d5d6f-5625-4320-8cda-b611c6ae580c
results:
  copy:
    cmd: juju scp etcd/0:/home/ubuntu/etcd-snapshots/etcd-snapshot-2016-11-09-02.41.47.tar.gz
      .
  snapshot:
    path: /home/ubuntu/etcd-snapshots/etcd-snapshot-2016-11-09-02.41.47.tar.gz
    sha256: 1dea04627812397c51ee87e313433f3102f617a9cab1d1b79698323f6459953d
    size: 68K
status: completed

$ juju scp etcd/0:/home/ubuntu/etcd-snapshots/etcd-snapshot-2016-11-09-02.41.47.tar.gz .

$ sha256sum etcd-snapshot-2016-11-09-02.41.47.tar.gz
```

Step 3: Deploy the new cluster leader, and attach the snapshot

```
juju deploy etcd new-etcd --resource snapshot=./etcd-snapshot-2016-11-09-02.41.47.tar.gz
```

Step 4: Re-Initialize the master with the data from the resource we just attached
in step 3.

```
juju run-action new-etcd/0 restore
```

Step 5: Scale and operate as required


# Known Limitations


#### TLS Defaults Warning (for trusty etcd charm users)
Additionally, this charm breaks with no backwards compat/upgrade path at the Trusty/Xenial
series boundary. Xenial forward will enable TLS by default. This is an incompatible break
due to the nature of peer relationships, and how the certificates are generated/passed off.

To migrate from Trusty to Xenial, the operator will be responsible for deploying the
Xenial etcd cluster, then issuing an etcd data dump on the trusty series, and importing
that data into the new cluster. This can be only be performed on a single node
due to the nature of how replicas work in Etcd.

Any issues with the above process should be filed against the charm layer in github.

#### Restoring from snapshot on a scaled cluster

Restoring from a snapshot on a scaled cluster will result in a broken cluster.
Etcd performs clustering during unit turn-up, and state is stored in Etcd itself.
During the snapshot restore phase, a new cluster ID is initialized, and peers
are dropped from the snapshot state to enable snapshot restoration. Please
follow the migration instructions above in the restore action description.

## Contributors

- Charles Butler &lt;[charles.butler@canonical.com](mailto:charles.butler@canonical.com)&gt;
- Mathew Bruzek  &lt;[mathew.bruzek@canonical.com](mailto:mathew.bruzek@canonical.com)&gt;
