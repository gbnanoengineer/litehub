#!/bin/sh
# Build litehub_<version>_all.deb
set -e
cd "$(dirname "$0")"
VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' src/litehub.py | head -1)
B=build/litehub_${VERSION}_all
rm -rf build && mkdir -p "$B/DEBIAN" "$B/usr/bin" "$B/usr/share/applications" "$B/usr/share/icons/hicolor/scalable/apps" "$B/usr/share/doc/litehub"
install -m755 src/litehub.py "$B/usr/bin/litehub"
install -m644 packaging/litehub.desktop "$B/usr/share/applications/litehub.desktop"
install -m644 packaging/litehub.svg "$B/usr/share/icons/hicolor/scalable/apps/litehub.svg"
install -m644 LICENSE "$B/usr/share/doc/litehub/copyright"
install -m644 README.md "$B/usr/share/doc/litehub/README.md"
sed "s/@VERSION@/$VERSION/" packaging/control > "$B/DEBIAN/control"
install -m755 packaging/postinst packaging/postrm "$B/DEBIAN/"
fakeroot dpkg-deb --build "$B" "build/litehub_${VERSION}_all.deb" >/dev/null
echo "Built build/litehub_${VERSION}_all.deb"
