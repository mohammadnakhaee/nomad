#!/bin/sh
version=`git describe --tags`
sed -i -e "s/nomad-gui-version-placeholder/$version/g" package.json
rm -f package.json-e