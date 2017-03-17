
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

test-convoluted:
	charm build -o tmp -r --no-local-layers
	tox -c tmp/builds/etcd/tox.ini
	rm -rf tmp

clean:
	rm -rf .tox
	rm -f .coverage
	rm -rf ./tmp

clean-all: clean
	rm -rf ${JUJU_REPOSITORY}/builds/etcd
