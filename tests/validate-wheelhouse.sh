#!/bin/bash

build_dir="$(mktemp -d)"
function cleanup { rm -rf "$build_dir"; }
trap cleanup EXIT

charm build . --build-dir "$build_dir" --debug
pip install -f "$build_dir/etcd/wheelhouse" --no-index --no-cache-dir "$build_dir"/etcd/wheelhouse/*