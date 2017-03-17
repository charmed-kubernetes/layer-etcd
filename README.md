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
Unit        Workload  Agent  Machine  Public address  Ports     Message
etcd/0*     active    idle   1        54.227.0.225    2379/tcp  Healthy with 3 known peers
etcd/1      active    idle   2        184.72.191.212  2379/tcp  Healthy with 3 known peers
etcd/2      active    idle   3        34.207.195.139  2379/tcp  Healthy with 3 known peers
```

# TLS

The ETCD charm supports TLS terminated endpoints by default. All efforts have
been made to ensure the PKI is as robust as possible.

Client certificates can be obtained by running an action on any of the cluster
members:

```shell
juju run-action etcd/12 package-client-certificates
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
cloud provides to us, which can be listed:
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
> Don't forget to `juju attach` the snapshot created in the snapshot action.

```
juju attach new-etcd snapshot=/path/to/etcd-backup
juju run-action new-etcd/0 restore
```

Once the restore action has completed, evaluate the cluster health. If the unit
is healthy, you may resume scaling the application to meet your needs.


- **param** target: destination directory to save the existing data.

- **param** skip-backup: Don't backup any existing data. (defaults to True)

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


# Limited egress operations

The etcd charm installs etcd as a snap package. You can supply an etcd.snap
resource to make this charm easily installable behind a firewall.

```
juju deploy /path/to/etcd
juju attach etcd etcd=/path/to/etcd.snap
```

### Post Deployment Snap Upgrades (if using the resource)

The charm if installed from a locally supplied resource will be locked into
that resource version until another is supplied and explicitly installed.

```
juju attach etcd etcd=/path/to/new/etcd.snap
juju run-action etcd/0 install
juju run-action etcd/1 install
```

# Migrate from Deb to Snap

> This only applies if you are upgrading an existing etcd charm deployment. New
> deployments will default to snap delivery. Migration will not be an issue in
> this scenario.

Revision 24 of etcd was the last published version installing etcd from the
debian packages. 25+ installs from the snap store (or resource). During the
migration process, you will be notified that a classic installation exists and
a manual migration must be run.

This is your opportunity to ensure state has been captured, and to plan for
downtime, as this migration process will stop and resume the application. This
service disruption can cause disruption in dependent applications.

### Starting the migration

The deb to snap migration process has been as automated as possible. Despite
the automatic backup mechanism during the migration process, you are still
encouraged to run a [snapshot](#Snapshot) before executing the upgrade.

Once you've completed your snapshot, you may begin the upgrade process. As this
action has been decoupled from the normal operational hooks of the charm, you
will need to individually upgrade each unit in series. Best practice would
be to migrate an individual unit at a time to ensure the cluster upgrades
appropriately without issue.

```
juju run-action etcd/0 snap-upgrade
```

Once the unit has completed upgrade, the unit's status message will return to
its normal health check messaging.

```
Unit        Workload  Agent  Machine  Public address  Ports     Message
etcd/0*     active    idle   1        54.89.190.93    2379/tcp  Healthy with 3 known peers
```

You can migrate from the debian locked 2.2.x to a 2.3.x or even 3.x etcd by
configuring the snap `channel` option on the charm before executing the
migration.  As expected, you can change the channel and update between channel
revisions at any time during normal operation of the charm.

```
juju config etcd channel=3.0/stable
juju run-action etcd/0 snap-upgrade
```


# Known Limitations

#### Moving from 2.x to 3.x and beyond

The etcd charm relies heavily on the snap package for etcd. In order to properly
migrate a 2.x series etcd deployment into 3.1 and beyond you will need to follow
a proper channel migration path. The initial deb to snap upgrade process will
place you in a 2.3 deployment.

You can migrate from 2.3 to 3.0

```
juju config etcd channel=3.0/stable
```

From the 3.0 channel you can migrate to 3.1 (current latest at time of writing)

```
juju config etcd channel=3.1/stable
```

You **MUST** perform the 2.3 => 3.0 before moving from 3.0 => 3.1  A migration
from 2.3 => 3.1 is not supported at this time.



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
