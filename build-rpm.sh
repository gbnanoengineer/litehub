#!/bin/sh
# Build litehub-<version>-1.noarch.rpm (needs: rpm-build). On Debian/Ubuntu: sudo apt install rpm
set -e
cd "$(dirname "$0")"
VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' src/litehub.py | head -1)
T=$(mktemp -d)
mkdir -p "$T/SOURCES" "$T/litehub-$VERSION"
cp -r src packaging README.md LICENSE "$T/litehub-$VERSION/"
tar -C "$T" -czf "$T/SOURCES/litehub-$VERSION.tar.gz" "litehub-$VERSION"
rpmbuild -bb packaging/litehub.spec --define "_topdir $T" --define "version $VERSION"
mkdir -p build && cp "$T"/RPMS/noarch/*.rpm build/
echo "Built: $(ls build/*.rpm)"
