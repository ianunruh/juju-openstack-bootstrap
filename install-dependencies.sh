#!/bin/bash
set -eux

export DEBIAN_FRONTEND=noninteractive

add-apt-repository -y ppa:juju/stable

apt-get update -q
apt-get install -yq juju-core python-dev python-pip libffi-dev libssl-dev libxml2-dev libxslt1-dev

pip install -q python-keystoneclient python-glanceclient python-swiftclient pyyaml glob2
