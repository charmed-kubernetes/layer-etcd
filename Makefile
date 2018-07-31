
build:
	charm build -r --no-local-layers

deploy: build
	juju deploy ${JUJU_REPOSITORY}/builds/etcd
	juju deploy cs:~containers/easyrsa
	juju add-relation etcd easyrsa

lint:
	tox --notest
	PATH=.tox/py34/bin:.tox/py35/bin flake8 reactive lib

upgrade: build
	juju upgrade-charm etcd --path=${JUJU_REPOSITORY}/builds/etcd

force: build
	juju upgrade-charm etcd --path=${JUJU_REPOSITORY}/builds/etcd --force-units

test-convoluted:
	/snap/bin/charm build -o ${HOME}/tmp -r --no-local-layers -l DEBUG
	tox -c ${HOME}/tmp/builds/etcd/tox.ini
	rm -rf ${HOME}/tmp

clean:
	rm -rf .tox
	rm -f .coverage
	rm -rf ./tmp

clean-all: clean
	rm -rf ${JUJU_REPOSITORY}/builds/etcd
