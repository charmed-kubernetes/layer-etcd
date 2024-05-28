# Etcd

Etcd is a highly available distributed key value store that provides a reliable
way to store data across a cluster of machines. Etcd gracefully handles master
elections during network partitions and will tolerate machine failure,
including the master.

Your applications can read and write data into etcd. A simple use-case is to
store database connection details or feature flags in etcd as key value pairs.
These values can be watched, allowing your app to reconfigure itself when they
change.

Advanced uses take advantage of the consistency guarantees to implement
database master elections or do distributed locking across a cluster of
workers.

Etcd allows storing data in a distributed hierarchical database with
observation.

This charm is maintained along with the components of Charmed Kubernetes. For full information,
please visit the [official Charmed Kubernetes docs](https://www.ubuntu.com/kubernetes/docs/charm-etcd).

## Build Charm
```bash
charmcraft pack
```

This command will create a charm which you can deploy using juju.
