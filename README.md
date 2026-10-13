# LiteHub

Lightweight all-in-one hub for Ubuntu: WhatsApp, Telegram, Slack, Discord, Gmail, Outlook, Teams,
Messenger, any custom site. Qt + Chromium engine (no Electron). Unofficial.

- **Multiple accounts**: add the same service many times (`+`, Ctrl+N); each has an isolated login.
- **WhatsApp**: link as a companion device (phone > Settings > Linked devices > scan QR).
- **Calls / video / screen share**: Chromium WebRTC; screen picker appears when a site asks.
- **Theme**: dark / light / system (sun/moon button in the sidebar, or Preferences). Real site icons are used for each service.
- **Notifications per app**: right-click a service (or tray > *Notifications from…*) to choose which apps may notify you. The tray icon shows an unread badge; its menu lists every service with unread counts and opens it on click.
- **Downloads**: one shared manager (Ctrl+Shift+D) with Open / Show in folder; notification has an Open button.
- **Low RAM**: services load lazily; right-click a service > *Sleep*, or untick *Keep running in background*
  and it unloads automatically after N idle minutes (Preferences).
- **Customise**: Preferences (Ctrl+,), `~/.config/litehub/config.json`, global `custom.css`/`custom.js`,
  per-service `~/.config/litehub/services/<id>.css|js`. Rename the app: change `APP_NAME` in `src/litehub.py`.
- Flags: `--minimized`, `--debug`, `--reset` (wipes all logins).

Shortcuts: Alt+1..9 switch service, Ctrl+Tab next, Ctrl+R reload, Ctrl+/- zoom, Ctrl+Q quit.
Tray icon on GNOME needs the AppIndicator extension.

## Install
| Format | Command |
|---|---|
| Ubuntu/Debian `.deb` | `sudo apt install ./litehub_0.4.0_all.deb` |
| Fedora/RHEL `.rpm` | `sudo dnf install ./litehub-0.4.0-1.noarch.rpm` |
| Flatpak | `flatpak install --user ./litehub.flatpak` then `flatpak run io.github.gbnanoengineer.LiteHub` |

Packages are built by GitHub Actions on every push (Actions tab > artifacts) and attached to a release when you push a `v*` tag.
Local builds: `./build.sh` (deb), `./build-rpm.sh` (rpm, needs `rpm`), flatpak: `flatpak-builder --user --install --force-clean build-dir packaging/flatpak/io.github.gbnanoengineer.LiteHub.yml`.

## License
MIT
