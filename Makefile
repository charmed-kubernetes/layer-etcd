
build:
	charm build -r --no-local-layers

deploy: build
	juju deploy cs:~containers/easyrsa
	juju deploy ${JUJU_REPOSITORY}/builds/etcd
	juju add-relation etcd easyrsa

upgrade: build
	juju upgrade-charm etcd --path=${JUJU_REPOSITORY}/builds/etcd

force: build
	juju upgrade-charm etcd --path=${JUJU_REPOSITORY}/builds/etcd --force-units

