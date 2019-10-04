
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

clean:
	@echo "Cleaning files"
	@rm -f .coverage .unit-state.db
	@find . -name "*.pyc" -type f -exec rm -f '{}' \;
	@find . -name "__pycache__" -type d -prune -exec rm -rf '{}' \;
	@rm -rf ./.tox
	@rm -rf ./.pytest_cache

clean-all: clean
	rm -rf ${JUJU_REPOSITORY}/builds/etcd
