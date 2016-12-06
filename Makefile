
build:
	charm build -r --no-local-layers

deploy: build
	juju deploy ${JUJU_REPOSITORY}/builds/etcd
	juju deploy cs:~containers/easyrsa
	juju add-relation etcd easyrsa

lint:
	/usr/bin/python3 -m flake8 reactive lib

upgrade: build
	juju upgrade-charm etcd --path=${JUJU_REPOSITORY}/builds/etcd

force: build
	juju upgrade-charm etcd --path=${JUJU_REPOSITORY}/builds/etcd --force-units

test-convoluted: build
	tox -c ${JUJU_REPOSITORY}/builds/etcd/tox.ini

clean:
	rm -rf .tox
	rm -f .coverage

clean-all: clean
	rm -rf ${JUJU_REPOSITORY}/builds/etcd
