# Etcd

Etcd is a highly available distributed key value store that provides a reliable way to store data across a cluster of machines. Etcd gracefully handles master elections during network partitions and will tolerate machine failure, including the master.

Your applications can read and write data into etcd. A simple use-case is to store database connection details or feature flags in etcd as key value pairs. These values can be watched, allowing your app to reconfigure itself when they change.

Advanced uses take advantage of the consistency guarantees to implement database master elections or do distributed locking across a cluster of workers.

Etcd allows storing data in a distributed hierarchical database with observation.

# Usage

We can deploy a single node easily with

```shell
juju deploy etcd
```
Add and capacity with:

```shell
juju add-unit -n 2 etcd
```

Its recommended to run an odd number of machines as it has greater redundancy than even number (ie. 4, you can lose 1 before quorum is lost, where as 5, you can 2).

# The charm told me to see the README

## Usage with your own binaries

This charm supports resources, which means you can supply your own release of
etcd and etcdctl to this charm. Which by nature makes it highly deployable on
multiple architectures.

### Supply your own binaries

```shell
juju upgrade-charm etcd --resource etcd=./path/to/etcd --reosurce etcdtcl=./path/to/etcdctl
juju list-resources etcd
```

You will see your binaries have been provided by username@local, and the charm
will reconfigure itself to deploy the provided binaries.

### If you do not have the binaries

If you are simply deploying etcd, and the charm has halted demanding resources by
telling you to consult the READJE, you can use a script contained in the charm
itself.

```shell
charm pull etcd
cd etcd
make fetch_resources
...
cd resources
cd tar xvfz etcd*.tar.gz
```

You can then upgrade the charm using the resources found in this extracted archive.
Only the binaries will be necessary, you can safely ignore any additional files.

# Health
Health of the cluster can be checked by verified via juju actions

```shell
juju action do etcd/0 health
<return response uuid>
juju action fetch <uuid>

```


# Known Limitations

Scaling up works incredibly well. Scaling down however has proven problematic.
The nodes do their best attempt to self-unregister; however the cluster can find
itself in an inconsistent state with the current peering mechanisms.

This is a known issue and you are encouraged to only scale Etcd up until [this
problem has been resolved](https://github.com/juju-solutions/layer-etcd/issues/5).

This charm requires resources to be provided to the charm in order to deploy
on trusty hosts. This requires juju 2.0 or greater.


## Contributors

- Charles Butler &lt;[charles.butler@canonical.com](mailto:charles.butler@canonical.com)&gt;
