# Tessera

Lightweight all-in-one hub for Linux: WhatsApp, Telegram, Slack, Discord, Messenger, Instagram or any website.
Electron + Node, current Chromium engine, no Qt. Unofficial.

- **Looks like real Chrome**: the engine reports a normal Chrome user agent and client hints, so sites do not say
  "unsupported browser". WebRTC calls, video and H.264 work; screen share uses the desktop portal on Wayland.
- **Google apps, one login**: add Gmail, Google Meet, Calendar and Drive; when you add a second Google app, pick *Same login as Gmail* and you sign in once. Choose *New account* to keep another Google account separate. Gmail shows its inbox unread count.
- **Multiple accounts**: add the same service many times (`+`, Ctrl+N); each has an isolated login.
- **Low RAM**: services load lazily; right-click a service > *Sleep*, or untick *Keep running in background*
  and it unloads automatically after N idle minutes (Preferences).
- **Tray + badges**: unread counts from page titles on each service icon, on the tray icon and in its menu.
- **Per-app notifications**, downloads to `~/Downloads` with an Open-folder notification, dark/light/system theme.
- **Customise**: global `custom.css` and per-service `services/<id>.css` in `~/.config/tessera/`.

Shortcuts: Alt+1..9 switch service, Ctrl+Tab next, Ctrl+R reload, Ctrl+/- zoom, Ctrl+, preferences, F12 devtools, Ctrl+Q quit.
Flags: `--minimized`, `--tessera-debug`. Tray icon on GNOME needs the AppIndicator extension.

Not in 1.0: the built-in IMAP mail client from the Qt versions (0.x).

## Develop
```sh
npm install
npm start            # run
npm run icons        # regenerate assets/icons (needs python3-pil)
npm run dist         # .deb, .rpm and .AppImage in dist/
```

## Install
Download the `.deb`, `.rpm` or `.AppImage` from the Releases page, then e.g. `sudo apt install ./tessera_1.0.0_amd64.deb`.

## License
MIT
