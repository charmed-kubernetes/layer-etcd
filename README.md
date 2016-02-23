# Etcd

> This charm was built from layers! To see the developer docs see `hacking.md` in
the charm root.

### TODO

Fill this section out

# Known Limitations

Scaling up works incredibly well. Scaling down however has proven problematic.
The nodes do their best attempt to self-unregister; however the cluster can find
itself in an inconsistent state with the current peering mechanisms.

This is a known issue and you are encouraged to only scale Etcd up until this
problem has been resolved. *Insert Link Here*

## Contributors

- Charles Butler &lt;[charles.butler@canonical.com](mailto:charles.butler@canonical.com)&gt;
