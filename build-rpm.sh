#!/bin/sh
# Build tessera-<version>-1.noarch.rpm (needs: rpm-build). On Debian/Ubuntu: sudo apt install rpm
set -e
cd "$(dirname "$0")"
VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' src/tessera.py | head -1)
T=$(mktemp -d)
mkdir -p "$T/SOURCES" "$T/tessera-$VERSION"
cp -r src packaging README.md LICENSE "$T/tessera-$VERSION/"
tar -C "$T" -czf "$T/SOURCES/tessera-$VERSION.tar.gz" "tessera-$VERSION"
rpmbuild -bb packaging/tessera.spec --define "_topdir $T" --define "version $VERSION"
mkdir -p build && cp "$T"/RPMS/noarch/*.rpm build/
echo "Built: $(ls build/*.rpm)"
