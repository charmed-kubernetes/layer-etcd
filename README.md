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




# Known Limitations

Scaling up works incredibly well. Scaling down however has proven problematic.
The nodes do their best attempt to self-unregister; however the cluster can find
itself in an inconsistent state with the current peering mechanisms.

This is a known issue and you are encouraged to only scale Etcd up until this
problem has been resolved. *Insert Link Here*

## Contributors

- Charles Butler &lt;[charles.butler@canonical.com](mailto:charles.butler@canonical.com)&gt;
