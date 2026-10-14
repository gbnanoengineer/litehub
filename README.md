# Tessera

Lightweight all-in-one hub for Ubuntu: WhatsApp, Telegram, Slack, Discord, Gmail, Outlook, Teams,
Messenger, any custom site. Qt + Chromium engine (no Electron). Unofficial.

- **Mail (built in)**: Gmail, Outlook, Yahoo, iCloud or any IMAP account via an *app password* - folders, read, reply, compose, attachments, delete, unread badge + new-mail notifications. Passwords go to the system keyring (`secret-tool`). HTML mail is shown without scripts or remote content. (Google/Microsoft block embedded web sign-in, so there are no Gmail/Outlook/Teams web tiles.)
- **Multiple accounts**: add the same service many times (`+`, Ctrl+N); each has an isolated login.
- **WhatsApp**: link as a companion device (phone > Settings > Linked devices > scan QR).
- **Calls / video / screen share**: Chromium WebRTC; screen picker appears when a site asks.
- **Theme**: dark / light / system (sun/moon button in the sidebar, or Preferences). Real site icons are used for each service.
- **Notifications per app**: right-click a service (or tray > *Notifications from…*) to choose which apps may notify you. The tray icon shows an unread badge; its menu lists every service with unread counts and opens it on click.
- **Downloads**: one shared manager (Ctrl+Shift+D) with Open / Show in folder; notification has an Open button.
- **Low RAM**: services load lazily; right-click a service > *Sleep*, or untick *Keep running in background*
  and it unloads automatically after N idle minutes (Preferences).
- **Customise**: Preferences (Ctrl+,), `~/.config/tessera/config.json`, global `custom.css`/`custom.js`,
  per-service `~/.config/tessera/services/<id>.css|js`. Rename the app: change `APP_NAME` in `src/tessera.py`.
- Flags: `--minimized`, `--debug`, `--reset` (wipes all logins).

Shortcuts: Alt+1..9 switch service, Ctrl+Tab next, Ctrl+R reload, Ctrl+/- zoom, Ctrl+Q quit.
Tray icon on GNOME needs the AppIndicator extension.

## Always the latest engine, auto-updating
The `.deb` downloads the current Chromium (PyQt6 + Qt WebEngine) into `~/.local/share/tessera/venv` at install time and
refreshes it automatically (at most once a day, before the app starts). Force it with `tessera --update-engine`.
Tessera itself shows a notification when a newer GitHub release exists (`check_updates` in config.json).

## Download
Get the latest `.deb`, `.rpm` and `.flatpak` from the **[Releases page](https://github.com/gbnanoengineer/tessera/releases/latest)**.

## Install
| Format | Command |
|---|---|
| Ubuntu/Debian `.deb` | `sudo apt install ./tessera_0.7.1_all.deb` |
| Fedora/RHEL `.rpm` | `sudo dnf install ./tessera-0.7.1-1.noarch.rpm` |
| Flatpak | `flatpak install --user ./tessera.flatpak` then `flatpak run io.github.gbnanoengineer.Tessera` |

Packages are built by GitHub Actions on every push (Actions tab > artifacts) and attached to a release when you push a `v*` tag.
Local builds: `./build.sh` (deb), `./build-rpm.sh` (rpm, needs `rpm`), flatpak: `flatpak-builder --user --install --force-clean build-dir packaging/flatpak/io.github.gbnanoengineer.Tessera.yml`.

## License
MIT
