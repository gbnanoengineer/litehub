#!/bin/sh
# Build tessera_<version>_all.deb
set -e
cd "$(dirname "$0")"
VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' src/tessera.py | head -1)
B=build/tessera_${VERSION}_all
rm -rf build && mkdir -p "$B/DEBIAN" "$B/usr/bin" "$B/usr/share/applications" "$B/usr/share/icons/hicolor/scalable/apps" "$B/usr/share/doc/tessera"
install -m755 src/tessera.py "$B/usr/bin/tessera"
install -m644 packaging/tessera.desktop "$B/usr/share/applications/tessera.desktop"
install -m644 packaging/tessera.svg "$B/usr/share/icons/hicolor/scalable/apps/tessera.svg"
install -m644 LICENSE "$B/usr/share/doc/tessera/copyright"
install -m644 README.md "$B/usr/share/doc/tessera/README.md"
sed "s/@VERSION@/$VERSION/" packaging/control > "$B/DEBIAN/control"
install -m755 packaging/postinst packaging/postrm "$B/DEBIAN/"
fakeroot dpkg-deb --build "$B" "build/tessera_${VERSION}_all.deb" >/dev/null
echo "Built build/tessera_${VERSION}_all.deb"
